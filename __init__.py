from binaryninja import *


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

def get_type_deps(bv, tobj, tname, gt):
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
            deps |= get_type_deps(bv, d_tobj, None, gt)
    elif tobj_type == NamedTypeReferenceType:
        # recurse for referenced type
        refobj = gt(bv, tname)
        if refobj is None:
            raise NameError(f"Could not find referenced type {tname}")
        deps = get_type_deps(bv, refobj, tname, gt)
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
    #TODO out_f = OpenFileNameField("Output File", ".py")
    get_form_input([types_f, rec_f, dbg_f, pre_f], "Type Export")

    if types_f.result is None or len(types_f.result) == 0:
        return False

    typenames = [x.strip() for x in types_f.result.split(',')]

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
        tdeps = get_type_deps(bv, tobj, tname, gt)

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
            print("DBG: circ least:", found, deps[found])

            for dname in list(deps[found]):
                # add the declaration (everything without the _fields_)
                print(dname, "just declaration")
                #TODO
                declared.append(dname)

                # remove all the dependencies, but not the entries
                for tname in deps:
                    if dname in deps[tname]:
                        deps[tname].remove(dname)
            


        # generate
        if found in declared:
            print(found, "just fields")
            #TODO
        else:
            print(found)
            #TODO

        # remove the dependencies on this one
        del deps[found]
        for tname in deps:
            if found in deps[tname]:
                deps[tname].remove(found)

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