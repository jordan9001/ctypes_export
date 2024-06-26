import fnmatch
import string
import enum
from binaryninja import *

header_template = """# generated from ctypes_export plugin
# report issues to https://github.com/jordan9001/ctypes_export/issues
import enum
import ctypes

# Generated for the following types:
'''
{intypes}
'''

"""

structunion_declaration_template = """class {madetypename}({kind}):
    _pack_ = 1

"""

structunion_template = """class {madetypename}({kind}):
    _pack_ = 1
    _fields_ = [
{items}    ]

"""

structunion_template_assert= """class {madetypename}({kind}):
    _pack_ = 1
    _fields_ = [
{items}    ]
assert ctypes.sizeof({madetypename}) == 0x{size:x}

"""

structunion_definition_template = """{madetypename}._fields_ = [
{items}    ]

"""

structunion_definition_template_assert = """{madetypename}._fields_ = [
{items}    ]
assert ctypes.sizeof({madetypename}) == 0x{size:x}

"""

structunion_line_template = """        ('{name}', {equiv}),{comment}
"""

enum_template = """class {madetypename}__ENUM(enum.IntEnum):
{items}
{madetypename} = ctypes.c_uint{intsz}

"""

enum_line_template = """    {name} = 0x{val:x}
"""

EMPTY_ITEMS = """    pass

"""

alias_declaration_template = """# Forward declaration for {madetypename}
# {real}
{madetypename} = {equiv}

"""

alias_template = """{madetypename} = {equiv}

"""

markdown_template = """
```py
{report}
```
"""

class TypeKind(enum.Enum):
    STRUCT = 1
    UNION = 2
    ENUM = 3
    ALIAS = 4

    def baseclass(self):
        if self == TypeKind.STRUCT:
            return "ctypes.Structure"
        if self == TypeKind.UNION:
            return "ctypes.Union"
        if self == TypeKind.ENUM:
            return "enum.IntEnum"
        raise KeyError(f"No baseclass for {self}")

class DefType(enum.Enum):
    FULL = 1
    FWD_STRUCT = 2
    FWD_OTHER = 3
    PART = 4

def get_type_kind(tobj, tname):
    tobj_type = type(tobj)
    
    if tobj_type == EnumerationType:
        return TypeKind.ENUM

    if tobj_type == StructureType:
        if tobj.type == StructureVariant.UnionStructureType:
            return TypeKind.UNION
        return TypeKind.STRUCT

    if tobj_type == NamedTypeReferenceType:
        return TypeKind.ALIAS

    if tobj_type in [ArrayType, BoolType, CharType, FloatType, FunctionType, IntegerType, PointerType, VoidType, WideCharType]:
        return TypeKind.ALIAS
    
    raise NotImplementedError(f"Unimplemented export of type with tobj_type {tobj_type}")

valid_var_letters = string.ascii_letters + string.digits + '_'
def make_type_name(name, prefix):
    name = str(name)
    name = ''.join([(x if x in valid_var_letters else '_') for x in name])

    name = prefix + name
    # if the name starts with a double under python does mangling, so prevent that
    if name.startswith("__"):
        name = "_q" + name 
    return name

def make_anon_name(structmem, nth, parent, parent_type):
    name = ""
    if isinstance(nth, str):
        name = f'{parent}__n{nth}'
    elif parent_type.type == StructureVariant.UnionStructureType:
        # can't use offset, have to use order index
        name = f'{parent}__u{nth}'
    else:
        name = f'{parent}__0x{structmem.offset:x}'
    return name

def get_structunion_preitems(tobj, tname, prefix, do_asserts):
    report = ""
    # define anonymous structures and unions for this type
    for i in range(len(tobj.members)):
        m = tobj.members[i]
        if type(m.type) in [StructureType, EnumerationType]:
            # this is not a NamedTypeReferenceType so it must be anonymous
            name = make_anon_name(m, i, tname, tobj)
            report += full_definition(name, m.type, prefix, do_asserts)
        elif type(m.type) in [ArrayType, FunctionType, PointerType]:
            # handle unnamed structures/enums used in pointers, arrays, functions
            # may require some recursing
            rec_list = [(f"{i}_{ii}",m.type.children[ii]) for ii in range(len(m.type.children))]

            while len(rec_list) > 0:
                i, c = rec_list[0]
                del rec_list[0]

                if type(c) in [StructureType, EnumerationType]:
                    name = make_anon_name(None, i, tname, None)
                    report += full_definition(name, c, prefix, do_asserts)
                elif type(c) in [ArrayType, FunctionType, PointerType]:
                    for j in range(len(c.children)):
                        rec_list.append((f"{i}_{j}", c.children[j]))
    
    return report

def structunion_line(structmem, nth, parent, parent_type, prefix, comment=""):
    name = structmem.name
    if len(name) == 0:
        name = f"__0x{structmem.offset:x}"

    equiv = None
    mobj_type = type(structmem.type)

    # if it is a structure or enum or named type, we can use our name
    if mobj_type == NamedTypeReferenceType:
        # use the name
        equiv = make_type_name(structmem.type.name, prefix)
    elif mobj_type == StructureType:
        equiv = make_type_name(make_anon_name(structmem, nth, parent, parent_type), prefix)
    elif mobj_type == EnumerationType:
        tref = structmem.type.registered_name
        if tref is None:
            equiv = make_type_name(make_anon_name(structmem, nth, parent, parent_type), prefix)
        else:
            equiv = make_type_name(tref.name, prefix)
    else:
        # ArrayType, BoolType, CharType, FloatType, FunctionType, IntegerType, PointerType, VoidType, WideCharType
        equiv = get_ctypes_equiv(structmem.type, prefix, parent, nth)

    if len(comment) > 0:
        comment = ' # ' + comment
    return structunion_line_template.format(name=name, equiv=equiv, comment=comment)

def get_union_items(tobj, tname, prefix):
    items = ""
    maxlen = 0
    for i in range(len(tobj.members)):
        m = tobj.members[i]
        if m.type.width > maxlen:
            maxlen = m.type.width
        items += structunion_line(m, i, tname, tobj, prefix)

    # pad to correct size
    if maxlen > tobj.width:
        print(f"Warning, union {tname} is too large, is {maxlen} bytes, but should be {tobj.width} bytes")

    if maxlen < tobj.width:
        items += structunion_line_template.format(name=f"_pad_to_0x{tobj.width:x}", equiv=f"ctypes.c_uint8 * 0x{tobj.width:x}", comment="")

    return items

def struct_padding(offset, size):
    items = ""
    end = offset + size
    while offset < end:
        sz = 0
        allsz = end - offset
        pt = ""
        equiv = ""
        # if align to 0x4
        # then align to 0x8 with a c_uint4
        # then fill with array in 0x10 sizes
        # then fill the rest
        if allsz < 4 or (offset & 0x3) != 0:
            sz = 1
            pt = ""
            equiv = "ctypes.c_uint8"
        elif allsz < 8 or (offset & 0x7) != 0:
            sz = 4
            pt = "4"
            equiv = "ctypes.c_uint32"
        elif allsz < 0x10:
            sz = 8
            pt = "8"
            equiv = "ctypes.c_uint64"
        else:
            sz = (end - offset) & (~(0x10 - 1))
            pt = "arr"
            equiv = f"ctypes.c_uint8 * 0x{sz:x}"
        
        items += structunion_line_template.format(name=f"pad_{pt}_0x{offset:x}", equiv=equiv, comment="")
        offset += sz
        
    return items

def get_struct_items(tobj, tname, prefix):
    items = ""
    # define fields
    offset = 0
    for i in range(len(tobj.members)):
        m = tobj.members[i]
        if offset > m.offset:
            # raise RuntimeError(f"Offsets disagree in structure?\n{offset} {m.offset}\n{repr(tobj.members)}")
            # apperantly this can happen sometimes?
            # we could convert this into a union, but for now just skip this other item
            continue
        while offset < m.offset:
            # add padding
            padsize = m.offset - offset
            items += struct_padding(offset, padsize)
            offset += padsize

        # add item
        items += structunion_line(m, i, tname, tobj, prefix, comment=f"0x{offset:x}")
        offset += m.type.width
        
    # pad at end
    while offset < tobj.width:
        # add padding
        padsize = tobj.width - offset
        items += struct_padding(offset, padsize)
        offset += padsize

    return items

def get_enum_items(tobj):
    # define enum options
    items = ""
    if len(tobj.members) == 0:
        return EMPTY_ITEMS
    # assumes no weird widths?
    mask = (( 1 << (8 * tobj.width)) - 1)
    for m in tobj.members:
        items += enum_line_template.format(name=m.name, val=m.value & mask)

    return items

def equiv_basetype(tobj, prefix, declared, gt):
    # tobj should always be a NamedTypeReferenceType in this function
    # deref all the way and get the best fit
    while type(tobj) == NamedTypeReferenceType:
        if tobj.name in declared:
            return make_type_name(tobj.name, prefix)
        tobj = gt(tobj.name)

    # now, depending on the type, we can set something up
    if type(tobj) == StructureType:
        # I guess just say it is an array of bytes of a certain size?
        return f"ctypes.c_uint8 * {tobj.width}"
    if type(tobj) == EnumerationType:
        if tobj.registered_name is None or tobj.registered_name.name not in declared:
            return f"ctypes.c_uint{tobj.width * 8}"
        else:
            return make_type_name(tobj.registered_name.name, prefix)

    # otherwise drill down a bit more as possible
    return get_ctypes_equiv(tobj, prefix, tobj.name, 0, declared, gt)

def get_ctypes_equiv(tobj, prefix, parent, nth, declared=None, gt=None):
    # get ctypes equivalent string
    # if declared is not None, it means we want to do our best, but fall back to base types

    tobj_type = type(tobj)
    if tobj_type == NamedTypeReferenceType:
        if declared is not None and tobj.name not in declared:
            return equiv_basetype(tobj, prefix, declared, gt)
        return make_type_name(tobj.name, prefix)
    elif tobj_type == ArrayType:
        subtype = get_ctypes_equiv(tobj.element_type, prefix, parent, f"{nth}_0", declared, gt)
        return f"({subtype}) * {tobj.count}"
    elif tobj_type in [BoolType, CharType, IntegerType, WideCharType]:
        signed = False
        if tobj_type == IntegerType:
            signed = tobj.signed

        width = tobj.width
        if width not in [1,2,4,8]:
            raise NotImplementedError(f"got a int-like with a weird width: {width} {repr(tobj)}")

        return f"ctypes.c_{'u' if not signed else ''}int{width * 8}"
    elif tobj_type == PointerType:
        # check for void target
        targ = tobj.target
        if type(targ) == VoidType:
            return "ctypes.c_void_p"
        if declared is not None and type(targ) == NamedTypeReferenceType and targ.name not in declared:
            return "ctypes.c_void_p"

        subtype = get_ctypes_equiv(tobj.target, prefix, parent, f"{nth}_0", declared, gt)
        return f"ctypes.POINTER({subtype})"
    elif tobj_type == FloatType:
        floatsz = "float"
        if tobj.width == 4:
            floatsz = "float"
        elif tobj.width == 8:
            floatsz = "double"
        else:
            raise NotImplementedError(f"Unknown float with width {tobj.width} {repr(tobj)}")
        return f"ctypes.c_{floatsz}"
    elif tobj_type == FunctionType:
        restype = get_ctypes_equiv(tobj.return_value, prefix, parent, f"{nth}_0", declared, gt)
        argtypes = ','.join([get_ctypes_equiv(tobj.parameters[i].type, prefix, parent, f"{nth}_{i+1}", declared, gt) for i in range(len(tobj.parameters))])
        #TODO calling convention information instead of just CFUNCTYPE
        return f"ctypes.CFUNCTYPE(({restype}), {argtypes})"
    elif tobj_type == VoidType:
        # probably a function return value
        # just use void* whatever
        return "ctypes.c_void_p"
    elif tobj_type in [StructureType, EnumerationType]:
        # this seems a brittle way to do this :/
        name =  make_type_name(make_anon_name(None, str(nth), parent, None), prefix)
        return name
    else:
        # not in NamedTypeReference, ArrayType, BoolType, CharType, FloatType, FunctionType, IntegerType, PointerType, WideCharType
        maybename =  make_anon_name(None, str(nth), parent, None)
        raise NotImplementedError(f"Unimplemented type type in get_ctypes_equiv: {repr(tobj)}, {maybename}")
    
def declaration(typename, typeobj, prefix, declared, gt, do_asserts):
    kind = get_type_kind(typeobj, typename)

    if kind == TypeKind.ENUM:
        return full_definition(typename, typeobj, prefix, do_asserts), False

    if kind == TypeKind.ALIAS:
        real = full_definition(typename, typeobj, prefix, do_asserts)
        # I can't forward declare aliases the way I am doing them
        # but I can't full define them, because they can have dependencies
        # so we alias to some equivalent type that is the same width
        fake_equiv = get_ctypes_equiv(typeobj, prefix, typename, 0, declared, gt)

        return alias_declaration_template.format(real=real, madetypename=make_type_name(typename, prefix), equiv=fake_equiv), True

    # STRUCT and UNION
    return structunion_declaration_template.format(madetypename=make_type_name(typename, prefix), kind=kind.baseclass()), True

def part_definition(typename, typeobj, prefix, do_asserts):
    kind = get_type_kind(typeobj, typename)

    if kind == TypeKind.ENUM:
        raise Exception(f"Unexpected type needing a partial definition? {kind}")

    if kind == TypeKind.ALIAS:
        # overwrite the stand in that has the equivalent sized types
        return full_definition(typename, typeobj, prefix, do_asserts)

    preitems = get_structunion_preitems(typeobj, typename, prefix, do_asserts)

    items = ""
    if kind == TypeKind.STRUCT:
        items = get_struct_items(typeobj, typename, prefix)
    elif kind == TypeKind.UNION:
        items = get_union_items(typeobj, typename, prefix)

    # this doesn't always work, if the type or an alias are used as a non-pointer before this
    if do_asserts:
        return preitems + structunion_definition_template_assert.format(madetypename=make_type_name(typename, prefix), items=items, size=typeobj.width)
    else:
        return preitems + structunion_definition_template.format(madetypename=make_type_name(typename, prefix), items=items)
        

def full_definition(typename, typeobj, prefix, do_asserts):
    kind = get_type_kind(typeobj, typename)

    if kind in [TypeKind.STRUCT, TypeKind.UNION]:

        preitems = get_structunion_preitems(typeobj, typename, prefix, do_asserts)

        items = ""
        if kind == TypeKind.STRUCT:
            items = get_struct_items(typeobj, typename, prefix)
        elif kind == TypeKind.UNION:
            items = get_union_items(typeobj, typename, prefix)

        if do_asserts:
            return preitems + structunion_template_assert.format(madetypename=make_type_name(typename, prefix), kind=kind.baseclass(), items=items, size=typeobj.width)
        else:
            return preitems + structunion_template.format(madetypename=make_type_name(typename, prefix), kind=kind.baseclass(), items=items)

    if kind == TypeKind.ENUM:
        items = get_enum_items(typeobj)
        return enum_template.format(madetypename=make_type_name(typename, prefix), items=items, intsz=(typeobj.width * 8))

    if kind == TypeKind.ALIAS:
        equiv = get_ctypes_equiv(typeobj, prefix, typename, 0)
        return alias_template.format(madetypename=make_type_name(typename, prefix), equiv=equiv)
    raise NotImplementedError(f"Unimplemented definition for kind {kind}")

def get_type(bv, typename):
    # should we check and warn if there is a _1 variant?
    return bv.get_type_by_name(typename)

def get_type_dbg(bv, typename):
    #TODO for some reason some types end up on a path that forces the non-dbg version even when the other exists

    res = bv.debug_info.get_types_by_name(str(typename))
    if len(res) == 0:
        # try falling back to the rest of the types
        return get_type(bv, typename)
        #return None
    if len(res) > 1:
        print(f"Warning: type '{typename}' is provided by multiple debug parsers: {', '.join([x[0] for x in res])}")

    return res[0][1]

def is_ptr_alias(tobj, gt):
    while type(tobj) == NamedTypeReferenceType:
        tobj = gt(tobj.name)

    if type(tobj) in [FunctionType, PointerType]:
        return True

    return False

def get_type_deps(tobj, tname, gt):
    strong_deps = set()
    weak_deps = set()
    tobj_type = type(tobj)

    #ArrayType, BoolType, CharType, EnumerationType, FloatType, FunctionType, IntegerType, NamedTypeReferenceType, PointerType, StructureType, VoidType, WideCharType

    if tobj_type in [ArrayType, FunctionType, PointerType, StructureType]:
        # go through children
        # do we need to be more specific? for example StructureType has .members ArrayType has .element_type, PointerType has .target, ...
        for d_tobj in tobj.children:
            if type(d_tobj) == NamedTypeReferenceType:
                # if this is a reference, add a dependency on the name
                # we need to find out if this is a strong dep or a weak dep
                if tobj_type in [FunctionType, PointerType]:
                    weak_deps.add(d_tobj.name)
                else:
                    strong_deps.add(d_tobj.name)
                continue
            if d_tobj.registered_name != None:
                # if this is known by a name, we want to capture that 
                # we need to find out if this is a strong dep or a weak dep
                if tobj_type in [FunctionType, PointerType]:
                    weak_deps.add(d_tobj.registered_name.name)
                else:
                    strong_deps.add(d_tobj.registered_name.name)
                continue
            # ignore base type deps with no name
            if type(d_tobj) in [BoolType, CharType, EnumerationType, FloatType, IntegerType, VoidType, WideCharType]:
                continue

            # otherwise we need to recurse and get the sub-types for dependencies
            child_strong_deps, child_weak_deps = get_type_deps(d_tobj, None, gt)
            if tobj_type in [FunctionType, PointerType]:
                # these are all made weak through a pointer
                weak_deps |= child_strong_deps | child_weak_deps
            else:
                strong_deps |= child_strong_deps
                weak_deps |= child_weak_deps
    elif tobj_type == NamedTypeReferenceType:
        # depend on the next step by it's name
        # find if it is a strong dep or a weak dep
        strong_deps.add(tobj.name)
    elif tobj_type in [BoolType, CharType, EnumerationType, FloatType, IntegerType, VoidType, WideCharType]:
        # base types, no dependencies
        pass
    else:
        raise NotImplementedError(f"Getting Dependancies not implemented for type type {str(tobj_type)}")

    return strong_deps, weak_deps

def update_deps(tname, full_def, strong_deps, weak_deps, rev_strong_deps, rev_weak_deps):

    # first remove weak dependencies on this type
    # if this is a fwd declaration, it allowed those types to be created now
    rwdlist = list(rev_weak_deps[tname])
    for othername in rwdlist:
        weak_deps[othername].remove(tname)
        rev_weak_deps[tname].remove(othername)

    if full_def:
        # if we have fully defined it, then we can just remove this from all lists

        wdlist = list(weak_deps[tname])
        for othername in wdlist:
            rev_weak_deps[othername].remove(tname)

        rsdlist = list(rev_strong_deps[tname])
        for othername in rsdlist:
            strong_deps[othername].remove(tname)

        sdlist = list(strong_deps[tname])
        for othername in sdlist:
            rev_strong_deps[othername].remove(tname)
        # don't remove these if it is a fwd declaration
        # because we still need to define it later
        del strong_deps[tname]
        del weak_deps[tname]
        del rev_strong_deps[tname]
        del rev_weak_deps[tname]

def get_order(types, strong_deps, weak_deps, rev_strong_deps=None, rev_weak_deps=None):
    # all *_deps should always have the same keys

    # first calc the rev_strong_deps and friends if needed

    if rev_strong_deps is None:
        rev_strong_deps = {}
        rev_weak_deps = {}
        for tname in strong_deps:
            rev_strong_deps[tname] = set()
            rev_weak_deps[tname] = set()
        for tname in strong_deps:
            for rd in strong_deps[tname]:
                rev_strong_deps[rd].add(tname)
            for rd in weak_deps[tname]:
                rev_weak_deps[rd].add(tname)

    predefd = []

    order = []
    while len(strong_deps) > 0:
        found = False

        best_score = None
        best = None

        for tname in strong_deps:
            sd_count = len(strong_deps[tname])
            wd_count = len(weak_deps[tname])
            rsd_count = len(rev_strong_deps[tname])
            rwd_count = len(rev_weak_deps[tname])
            is_structunion = type(types[tname]) == StructureType

            # first go through the ones we know we can, that have no dependencies

            if sd_count + wd_count == 0:
                dt = DefType.FULL
                if tname in predefd:
                    dt = DefType.PART
                order.append((tname, dt))

                update_deps(tname, True, strong_deps, weak_deps, rev_strong_deps, rev_weak_deps)
                found = True
                break

            if sd_count == 0 and wd_count == 1 and tname in weak_deps[tname]:
                # special test for items with one self dep

                dt = DefType.FWD_OTHER
                if is_structunion:
                    dt = DefType.FWD_STRUCT

                order.append((tname, dt))
                order.append((tname, DefType.PART))

                update_deps(tname, True, strong_deps, weak_deps, rev_strong_deps, rev_weak_deps)
                found = True
                break

            # otherwise we have gone through those we can do safely
            # now we need to choose something to forward declare to keep things moving

            # we want to end up with a ordered list of what we want to try to fwd decalre
            # it should be like:
            """
            Priority
                ordered by if it is a structure
                ordered by how much of an item it would ready (items with only wd)
                ordered by number of rev wd (more is better)
                ordered by lower sd_count
                ordered by lower rev sd
                ordered by lower wd
            """
            
            # ignore any that are already fwd declared
            if tname in predefd:
                continue

            ready_amt = 0
            # for everything that depends on this, see how many others they depend on
            for other in rev_weak_deps[tname]:
                o_ready_amt = len(weak_deps[other])
                if ready_amt == 0 or o_ready_amt < ready_amt:
                    ready_amt = o_ready_amt

            score = (is_structunion, ready_amt, rwd_count, sd_count, rsd_count, wd_count)

            if best_score is None:
                best_score = score
                best = tname
                continue

            # is_structunion
            if best_score[0] and not score[0]:
                continue
            if score[0] and not best_score[0]:
                best_score = score
                best = tname
                continue

            # ready_amt
            if (best_score[1] != 0) and (score[1] == 0 or score[1] > best_score[1]):
                continue
            if (score[1] != 0) and (best_score[1] == 0 or best_score[1] > score[1]):
                best_score = score
                best = tname
                continue

            # rwd_count
            if best_score[2] > score[2]:
                continue
            if score[2] > best_score[2]:
                best_score = score
                best = tname
                continue

            # sd_count
            if best_score[3] < score[3]:
                continue
            if score[3] < best_score[3]:
                best_score = score
                best = tname
                continue

            # rsd_count
            if best_score[4] < score[4]:
                continue
            if score[4] < best_score[4]:
                best_score = score
                best = tname
                continue

            # wd_count
            if best_score[5] < score[5]:
                continue
            if score[5] < best_score[5]:
                best_score = score
                best = tname
                continue

            # A tie!
            continue

        if found:
            continue

        # fwd declare best

        if best is None:
            print("Error: Unable to move forward")
            print(predefd)
            for tname in strong_deps:
                print(tname, strong_deps[tname], weak_deps[tname], sep='\n\t')
            raise RuntimeError("Strong Circular Dependency?")

        dt = DefType.FWD_OTHER
        if best_score[0]:
            dt = DefType.FWD_STRUCT

        order.append((best, dt))
        predefd.append(best)
        update_deps(best, False, strong_deps, weak_deps, rev_strong_deps, rev_weak_deps)

    return order

def export_some(bv):
    types_f = MultilineTextField("Type Names (newline separated, * allowed)")
    rec_f = ChoiceField("Include Dependant Types", ["Yes", "No"], 0)
    dbg_f = ChoiceField("Use Only Debug Types", ["Yes", "No"], 1)
    chk_f = ChoiceField("Add Size Asserts", ["Yes", "No"], 0)
    pre_f = TextLineField("Class Name Prefix", "")
    out_f = SaveFileNameField("Output File", "Python Files (*.py)", "")
    get_form_input([types_f, rec_f, dbg_f, chk_f, pre_f, out_f], "Type Export")

    if types_f.result is None or len(types_f.result) == 0:
        return False

    do_asserts = chk_f.result == 0
    dbg_only = dbg_f.result == 0
    do_recurse = rec_f.result == 0
    prefix = pre_f.result
    filename = out_f.result
    typesstr = types_f.result

    gt_choice = get_type_dbg if dbg_only else get_type

    gt = lambda tname: gt_choice(bv, tname)

    orig_types= typesstr.split('\n')

    typenames = []
    if '*' in typesstr or '?' in typesstr or '[' in typesstr:
        allnames = [x.strip() for x in typesstr.split('\n')]

        # get all type names, then do blob checks against all them
        alltypes = []               
        if dbg_only:
            alltypes = [x[0] for x in bv.debug_info.types]
        else:
            for id in bv.type_container.types.keys():
                # can I just str a QualifiedName like this? I think so
                alltypes.append(str(bv.type_container.get_type_name(id)))

        globnames = []
        typenames = set()
        for b in allnames:
            if '*' not in b and '?' not in b and '[' not in b:
                typenames.add(b)
            else:
                globnames.append(b)

        for tname in alltypes:
            for b in globnames:
                if fnmatch.fnmatch(tname, b):
                    typenames.add(tname)
                    break
        typenames = list(typenames)
    else:
        typenames = [x.strip() for x in typesstr.split('\n')]

    # show loading bar

    def export_types(report_prog):
        types = {}
        # this is edges for the dependency graph
        # because the output has to be in order
        strong_deps = {}
        # stong deps are real
        # weak deps are thorugh pointers
        weak_deps = {}
        for tname in typenames:
            tobj = gt(tname)
            if tobj is None:
                print(f"Error: Could not find type {tname}")
                show_message_box("Missing Type", f"Could not find needed type: {tname}", MessageBoxButtonSet.OKButtonSet, MessageBoxIcon.ErrorIcon)
                # this is a problem if this is a dependent type
                # this usually happens when we try to force debuginfo types
                # so we just fall back to all types
                raise KeyError(f"Could not find needed type {tname}")
            types[tname] = tobj

            # get dependencies
            strong_tdeps, weak_tdeps = get_type_deps(tobj, tname, gt)

            # recurse as needed
            if do_recurse:
                for d in strong_tdeps:
                    if d not in typenames:
                        typenames.append(d)
                for d in weak_tdeps:
                    if d not in typenames:
                        typenames.append(d)
            else:
                # if not recursing, we still want good order for deps between included types
                strong_tdeps = strong_tdeps.intersection(set(typenames))
                weak_tdeps = weak_tdeps.intersection(set(typenames))

            strong_deps[tname] = strong_tdeps
            weak_deps[tname] = weak_tdeps

            #print("DBG:", tname, "strong:", strong_deps[tname])
            #print("DBG:", tname, "weak:", weak_deps[tname])

            if not report_prog(len(types), len(types) + 300):
                # cancel
                return

        # now start generating our type definitions
        num_alltypes = len(types)

        # first we need to find an order that works
        types_order = get_order(types, strong_deps, weak_deps)

        report = header_template.format(intypes=', '.join(orig_types))

        declared = set()
        # gen report from order and types
        for tname, linekind in types_order:
            if linekind == DefType.FULL:
                report += full_definition(tname, types[tname], prefix, do_asserts)
            elif linekind == DefType.PART:
                report += part_definition(tname, types[tname], prefix, do_asserts)
            else:
                decl, _ = declaration(tname, types[tname], prefix, declared, gt, do_asserts)
                report += decl

            declared.add(tname)

            if not report_prog(len(declared), num_alltypes):
                # cancel
                return

        if len(filename) == 0:
            show_markdown_report("Type Definitions", markdown_template.format(report=report), report)
        else:
            with open(filename, "w") as fp:
                fp.write(report)
        
        print("ctypes export done")

        return
    
    res = run_progress_dialog("Sorting Types", True, export_types)

    if not res:
        print("ctypes export canceled")

    return res

#TODO
# - Option to export a whole type archive

PluginCommand.register("Export types to ctypes", "Export one or more types to ctypes", export_some)

# we could use TypePrinter.register()
# but this isn't really for viewing, it is for harnesses
# so probably best to just output the definitions