from binaryninja import *
import enum

header_template = """ # generated from ctypes_export Binary Ninja Plugin
import enum
import ctypes

"""

structunion_declaration_template = """class {prefix}{typename}({kind}):
    _pack_ = 1
"""

structunion_definition_template = """{prefix}{typename}._fields_ = [
    {items}
]
"""

structunion_template = """class {prefix}{typename}({kind}):
    _pack_ = 1
    _fields_ = [
        {items}
    ]
"""

structunion_definition_template = """{prefix}{typename}._fields_ = [
    {items}
]
"""

enum_template = """class {prefix}{typename}(enum.IntEnum):
{items}
"""

alias_template = """{prefix}{typename} = {equiv}"""

# global to select on getting types from system types or debug info
gt = None

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

def get_type_kind(bv, tobj, tname):
    tobj_type = type(tobj)
    
    if tobj_type == EnumerationType:
        return TypeKind.ENUM

    if tobj_type == StructureType:
        if tobj.type == StructureVariant.UnionStructureType:
            return TypeKind.UNION
        return TypeKind.STRUCT

    if tobj_type == NamedTypeReferenceType:
        refobj = gt(bv, tname)
        if refobj is None:
            raise NameError(f"Could not find referenced type {tname}")
        return get_type_kind(bv, refobj, tname)

    if tobj_type in [ArrayType, BoolType, CharType, FloatType, FunctionType, IntegerType, PointerType, VoidType, WideCharType]:
        return TypeKind.ALIAS
    
    raise NotImplementedError(f"Unimplemented export of type with tobj_type {tobj_type}")

def get_structure_preitems(tobj, tname, prefix):
    # define anonymous structures and unions for this type
    #TODO
    raise NotImplementedError()

def get_structure_items(tobj, tname, prefix):
    # define fields
    #TODO
    raise NotImplementedError()

def get_enum_items(tobj):
    # define enum options
    #TODO
    raise NotImplementedError()

def get_alias_equiv(tobj):
    # get ctypes equivalent string
    #TODO
    raise NotImplementedError()

def declaration(bv, typename, typeobj, prefix):
    print(f"DBG: declare {typename}")
    kind = get_type_kind(bv, typeobj, typename)

    if kind in [TypeKind.ENUM, TypeKind.ALIAS]:
        raise Exception(f"Unexpected type needing a forward declaration? {kind}")
    return structunion_declaration_template.format(prefix=prefix, typename=typename, kind=kind.baseclass())

def part_definition(bv, typename, typeobj, prefix):
    print(f"DBG: define {typename}")
    kind = get_type_kind(bv, typeobj, typename)

    if kind in [TypeKind.ENUM, TypeKind.ALIAS]:
        raise Exception(f"Unexpected type needing a partial definition? {kind}")

    preitems = get_structure_preitems(typeobj, typename, prefix)

    items = get_structure_items(typeobj, typename, prefix)

    return preitems + structunion_definition_template.format(prefix=prefix, typename=typename, items=items)

def full_definition(bv, typename, typeobj, prefix):
    print(f"DBG: {typename}")
    kind = get_type_kind(bv, typeobj, typename)

    if kind in [TypeKind.STRUCT, TypeKind.UNION]:

        preitems = get_structure_preitems(typeobj, typename, prefix)

        items = get_structure_items(typeobj, typename, prefix)

        return preitems + structunion_template.format(prefix=prefix, typename=typename, kind=kind.baseclass(), items=items)

    if kind == TypeKind.ENUM:
        items = get_enum_items(typeobj)
        return enum_template.format(prefix=prefix, typename=typename, items=items)

    if kind == TypeKind.ALIAS:
        equiv = get_alias_equiv(typeobj)
        return alias_template.format(prefix=prefix, typename=typename, equiv=equiv)
    raise NotImplementedError(f"Unimplemented definition for kind {kind}")

def get_type_dbg(bv, typename):
    res = bv.debug_info.get_types_by_name(typename)
    if len(res) == 0:
        return None
    if len(res) > 1:
        print(f"Warning: type '{typename}' is provided by multiple debug parsers: {', '.join([x[0] for x in res])}")

    return res[0][1]
    

def get_type(bv, typename):
    # should we check and warn if there is a _1 variant?
    return bv.get_type_by_name(typename)

def get_type_deps(bv, tobj, tname):
    deps = set()
    tobj_type = type(tobj)

    #ArrayType, BoolType, CharType, EnumerationType, FloatType, FunctionType, IntegerType, NamedTypeReferenceType, PointerType, StructureType, VoidType, WideCharType

    if tobj_type in [ArrayType, FunctionType, PointerType, StructureType]:
        # go through children
        # do we need to be more specific? for example StructureType has .members ArrayType has .element_type, PointerType has .target, ...
        for d_tobj in tobj.children:
            if type(d_tobj) == NamedTypeReferenceType:
                # if this is a reference, add a dependency on the name
                deps.add(d_tobj.name)
                continue
            if d_tobj.registered_name != None:
                # if this is known by a name, we want to capture that 
                deps.add(d_tobj.registered_name.name)
                continue
            # ignore base type deps with no name
            if type(d_tobj) in [BoolType, CharType, EnumerationType, FloatType, IntegerType, VoidType, WideCharType]:
                continue

            # otherwise we need to recurse and get the sub-types for dependencies
            deps |= get_type_deps(bv, d_tobj, None)
    elif tobj_type == NamedTypeReferenceType:
        # recurse for referenced type
        refobj = gt(bv, tname)
        if refobj is None:
            raise NameError(f"Could not find referenced type {tname}")
        deps = get_type_deps(bv, refobj, tname)
    elif tobj_type in [BoolType, CharType, EnumerationType, FloatType, IntegerType, VoidType, WideCharType]:
        # base types, no dependencies
        pass
    else:
        raise NotImplementedError(f"Getting Dependancies not implemented for type type {str(tobj_type)}")

    return deps

def export_some(bv):
    types_f = MultilineTextField("Type Names (comma separated)")
    rec_f = ChoiceField("Include Dependant Types", ["Yes", "No"], 0)
    dbg_f = ChoiceField("Use Only Debug Types", ["Yes", "No"], 1)
    pre_f = TextLineField("Class Name Prefix", "")
    out_f = OpenFileNameField("Output File", ".py", "")
    get_form_input([types_f, rec_f, dbg_f, pre_f, out_f], "Type Export")

    if types_f.result is None or len(types_f.result) == 0:
        return False

    typenames = [x.strip() for x in types_f.result.split(',')]

    global gt
    gt = get_type_dbg if dbg_f.result == 0 else get_type

    types = {}
    # this is edges for the dependency graph
    # because the output has to be in order
    deps = {}
    for tname in typenames:
        tobj = gt(bv, tname)
        if tobj is None:
            print(f"Error: Could not find type {tname}")
            continue
        types[tname] = tobj

        # get dependencies
        tdeps = get_type_deps(bv, tobj, tname)

        # recurse as needed
        if rec_f.result == 0:
            for d in tdeps:
                if d not in typenames:
                    typenames.append(d)
        else:
            # if not recursing, we still want good order for deps between included types
            tdeps = tdeps.intersection(set(typenames))

        deps[tname] = tdeps

    # now start generating our type definitions
    # we want to start with types that have no dependencies and continue until we have consumed all the types
    declared = []
    report = ""

    while len(deps) > 0:
        # find an item with no deps
        found = None
        least_amt = -1
        least = None
        for tname in deps:
            depcount = len(deps[tname])
            if least_amt == -1 or depcount < least_amt:
                least_amt = depcount
                least = tname
            if len(deps[tname]) == 0:
                found = tname
                break

        if found is None:
            # still just generate the definitions
            # Circular type dependencies detected, adding forward declarations
            found = least

            for dname in list(deps[found]):
                # add the declaration (everything without the _fields_)
                report += declaration(bv, dname, types[dname], pre_f.result)
                declared.append(dname)

                # remove all the dependencies, but not the entries
                for tname in deps:
                    if dname in deps[tname]:
                        deps[tname].remove(dname)
            
        # generate
        if found in declared:
            report += part_definition(bv, found, types[found], pre_f.result)
        else:
            report += full_definition(bv, found, types[found], pre_f.result)

        # remove the dependencies on this one
        del deps[found]
        for tname in deps:
            if found in deps[tname]:
                deps[tname].remove(found)

        
        print("filename", out_f.result)
        print(report)
        #TODO output file or as report if empty filename

    return True

#TODO
# - Option or command or blob pattern matching for exporting all types
# - Option to export all in a type archive

"""
class {prefix + typename}({basetype}):
    _pack_=1
    _fields_=[...]
"""

PluginCommand.register("Export types to ctypes", "Export one or more types to ctypes", export_some)

# we could use TypePrinter.register()
# but this isn't really for viewing, it is for harnesses
# so probably best to just output the definitions