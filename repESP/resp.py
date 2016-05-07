from fortranformat import FortranRecordWriter
import textwrap
import os
import numpy as np
from random import choice
from string import ascii_lowercase
from scipy.optimize import minimize_scalar, brentq

from .cube_helpers import InputFormatError, Atom, Molecule
from .resp_helpers import G09_esp
from .field_comparison import rms_and_rep
from . import charges

unset_charge = 42


def _read_respin(fn, ref_molecule=None):
    with open(fn, 'r') as inp:
        # Rewind to end of cntrl section
        line = inp.readline()
        while "&end" not in line:
            line = inp.readline()
        # Skip two lines ...
        for i in range(3):
            line = inp.readline()
        # ... and the third one will be `charge, iuniq`
        charge, iuniq = [int(elem) for elem in line.split()]

        # Create a molecule for consistency checks. It will not be returned, so
        # should be garbage-collected.
        molecule = Molecule(None)
        ivary_list = []
        for i, line in enumerate(inp):
            if len(line.split()) != 2:
                break
            atom = Atom(i+1, int(line.split()[0]))
            # Crucial bit: reading in ivary
            ivary_list.append(int(line.split()[1]))
            molecule.append(atom)

    # Check input file consistency
    if len(molecule) != iuniq:
        raise InputFormatError("The number of atoms {0} doesn't agree with"
                               " the `iuniq` value in the input file: {1}"
                               .format(len(molecule), iuniq))
    # Check the molecule against a reference molecule
    if ref_molecule is not None and molecule != ref_molecule:
        molecule.verbose_compare(ref_molecule)
        raise InputFormatError("The molecule in the .respin file differs "
                               "from the other molecule as shown above.")

    return ivary_list, charge, iuniq


common_respin_head = """
                     &cntrl

                     nmol = 1,
                     ihfree = 1,
                     ioutopt = 1,
                     """

common_respin_tail = """
                      &end
                         1.0
                     Resp charges for organic molecule
                     """


def _get_respin_content(respin_type, read_input_charges):
    """Check if respin type is implemented and return the input content"""
    if respin_type not in ['1', '2', 1, 2, 'h', 'u', 'd']:
        raise ValueError("`respin_type` {0} is not implemented.".format(
                         respin_type))

    result = "RESP input of type '{0}' generated by the repESP program".format(
        respin_type) + "\n" + textwrap.indent(textwrap.dedent(
            common_respin_head), ' ')

    if str(respin_type) == '1':
        result += " qwt = 0.00050,\n"
    elif str(respin_type) == '2':
        result += " qwt = 0.00100,\n"
    elif str(respin_type) in ['h', 'u', 'd']:
        # h_only RESP wouldn't constrain H charges anyway, but just in case
        result += " qwt = 0.00000,\n"

    if read_input_charges:
        result += " iqopt = 2,\n"
    elif str(respin_type) == '2':
        # These are the only incompatible options
        raise ValueError("Second stage of RESP requested without reading in "
                         "charges.")

    return result + textwrap.dedent(common_respin_tail)


def _write_modified_respin(respin_type, molecule, ivary_list, charge, iuniq,
                           fn_out, read_input_charges):
    with open(fn_out, 'w') as out:
        out.write(_get_respin_content(respin_type, read_input_charges))
        numbers = FortranRecordWriter('2I5')
        # `charge, iuniq` line
        print(numbers.write([charge, iuniq]), file=out)
        for atom, ivary in zip(molecule, ivary_list):
            print(numbers.write([atom.atomic_no, ivary]), file=out)

        print(file=out)


def _check_ivary(check_ivary, molecule, ivary_list):
    if not check_ivary:
        return
    print("\nPlease check if the following RESP input is what you want:\n")
    for atom, ivary in zip(molecule, ivary_list):
        print(atom, end='')
        if ivary < 0:  # RESP documentation states -1 but respgen uses -99
            print(", frozen")
        elif ivary > 0:
            print(", equivalenced to atom", molecule[ivary-1].label)
        else:
            print()


def _get_input_files(input_dir, respin1_fn=None, respin2_fn=None, esp_fn=None):
    """Check input directory for .respin and .esp files

    Parameters
    ----------
    input_dir : str
        The input directory.
    respin1_fn,respin2_fn,esp_fn : str, optional
        The filenames of the desired files. Default to `None`. If you don't
        wish to look for any of the files, leave its value at `None`. If you
        wish for any of the files to be detected automatically by its
        extension, set its filename to an empty string. An error will be thrown
        if there are no or more than one matching file.

    Returns
    -------
    List[str]
        The list of the paths to the files. If any of the input filename
        parameters was left at `None`, this list will be shorter than three
        elements. Note that the order of the returned paths will be as per the
        function header, rather than the order in which the keyword arguments
        are specified when calling this function.
    """
    if input_dir[-1] != '/':
        input_dir += '/'
    input_dir_contents = os.listdir(input_dir)
    extensions = ['.respin1', '.respin2', '.esp']
    result = []
    filenames = [respin1_fn, respin2_fn, esp_fn]
    for extension, fn in zip(extensions, filenames):
        if fn is None:
            continue
        candidates = [f for f in input_dir_contents if f.endswith(extension)]
        if fn:
            if fn in candidates:
                result.append(input_dir + fn)
                continue
            else:
                raise FileNotFoundError("The file {0} was not found in the "
                                        "input directory {1}".format(
                                            fn, input_dir))
        if not len(candidates):
            raise FileNotFoundError(
                "The input directory {0} doesn't contain any {1} files. If "
                "your desired file has a different extension, please specify "
                "the full filename.".format(input_dir, extension))
        if len(candidates) > 1:
            raise InputFormatError(
                "{0} {1} files found in the input directory {2}. Please "
                "specify the filename of the file to be used."
                .format(len(candidates), extension, input_dir))

        result.append(input_dir + candidates[0])
    return result


def run_resp(input_dir, calc_dir_path, resp_type='two_stage', inp_charges=None,
             check_ivary=True, respin1_fn="", respin2_fn="", esp_fn=""):
    """Runs RESP fitting and returns a molecule updated with resulting charges

    The necessary input files (``.esp``, ``.respin1`` and ``.respin2``) will be
    found in the input directory by extension. A new directory
    ``calc_dir_path`` will be created to keep all the intermediate and output
    files of the ``resp`` program.

    Parameters
    ----------
    input_dir : str
        Directory containing the input files.
    calc_dir_path : str
        Path to the new directory to be created.
    resp_type : {'two_stage', 'h_only', 'unrest', 'dict'}, optional
        The default ``two_stage`` option requests the normal two-stage RESP
        fitting. The ``ivary`` options are taken unaltered from the two
        original ``.respin`` files.

        The three options ``h_only``, ``unrest`` and ``dict`` request
        unconstrained (in terms of charge magnitude) optimization through
        one-stage RESP with zero restraint weight (``qwt``). ``h_only`` freezes
        all atoms except for hydrogens at input values. ``dict`` freezes only
        the atoms which are specified through the input charges
        (``inp_charges``). All three options read atom equivalence from the
        ``.respin`` files (``ivary`` values). To verify that equivalence is as
        expected, leave the ``check_ivary`` option enabled.

        ..
            The equivalence logic is explained somewhat inconsistently in the
            RESP papers but I've additionally re-engineered the ``resp``
            program's logic to be sure that reading both the ``respin`` files
            will give the desired behaviour. In fact, it's pretty simple. In
            the first stage atoms of the methyl and methylene groups are free,
            while all the others are equivalenced. In the second stage the
            former are equivalenced, while all the others are frozen.

    inp_charges : List[float], optional
        The input charges. Defaults to ``None``, which causes no ``iqopt``
        command being specified in the ``&cntrl`` section of the ``.respin``
        file. This causes it to default to 1 and 'reset all initial charges to
        zero'.
    check_ivary : bool, optional
        Verbosely report the RESP ``ivary`` actions to be performed by the
        ``resp`` program and ask the user if this is desired behaviour (no
        prompt). This is recommended as the equivalence information is taken
        from the ``.respin`` files, which are generated externally (likely by
        the ``respgen`` program) and, for one-stage RESP (``h_only`` or
        ``unrest``), additionaly modified by this program.
    respin1_fn,respin2_fn,esp_fn : str, optional
        The filenames of input files. These should be specified if there are
        more files with the same extension in the input directory.

    Returns
    -------
    Molecule
        Molecule created based on the ``.esp`` input file, updated with RESP
        charges.

    """
    if calc_dir_path[-1] != '/':
        calc_dir_path += '/'
    os.mkdir(calc_dir_path)
    respin1_fn, respin2_fn, esp_fn = _get_input_files(input_dir, respin1_fn,
                                                      respin2_fn, esp_fn)
    g09_esp = G09_esp(esp_fn)
    molecule = g09_esp.molecule
    if inp_charges is not None and len(inp_charges) != len(molecule):
        raise InputFormatError("The list of input charges is of length {0} but"
                               " the molecule considered has {1} atoms."
                               .format(len(inp_charges), len(molecule)))
    # Create the corrected .esp file
    g09_esp.field.write_to_file(calc_dir_path + "corrected.esp", molecule)
    # Dump the input charges
    if inp_charges is not None:
        charges._update_molecule_with_charges(molecule, inp_charges,
                                              'resp_inp')
        charges.dump_charges_to_qout(molecule, 'resp_inp', calc_dir_path +
                                     "input.qout")

    if resp_type == 'two_stage':
        charges_out_fn = _resp_two_stage(
            calc_dir_path, respin1_fn, respin2_fn, molecule, check_ivary,
            inp_charges is not None)
    elif resp_type in ['h_only', 'unrest', 'dict']:
        charges_out_fn = _resp_one_stage(resp_type[0], calc_dir_path,
                                         respin1_fn, respin2_fn, molecule,
                                         check_ivary, inp_charges)
    else:
        raise ValueError("RESP fitting type '{0}' was not recognized."
                         .format(resp_type))

    # Update the molecule with new 'resp' charges
    charges.update_with_charges('resp', calc_dir_path + charges_out_fn,
                                molecule, verbose=False)

    return molecule


def _resp_one_stage(resp_type, calc_dir_path, respin1_fn, respin2_fn, molecule,
                    check_ivary, inp_charges):
    """A common function for one-stage RESP ('h_only' and 'unrest')

    Atom equivalence will be taken from the ``.respin`` files (``ivary``
    values).
    """
    read_input_charges = inp_charges is not None
    # MODIFY THE .RESPIN FILE
    # Read in .respin1
    ivary_list1, charge1, iuniq1 = _read_respin(respin1_fn,
                                                ref_molecule=molecule)
    # Read in .respin2
    ivary_list2, charge2, iuniq2 = _read_respin(respin2_fn,
                                                ref_molecule=molecule)
    assert charge1 == charge2
    assert iuniq1 == iuniq2
    # Modify ivary list and write to new input file
    ivary_list = _modify_ivary_list(resp_type, molecule, ivary_list1,
                                    ivary_list2, inp_charges)
    _check_ivary(check_ivary, molecule, ivary_list)
    _write_modified_respin(resp_type, molecule, ivary_list, charge1, iuniq1,
                           calc_dir_path + "input.respin",
                           read_input_charges=read_input_charges)

    # RUN RESP
    input_charges_option = "-q input.qout " if read_input_charges else ""
    os.system("cd {0}; resp -i input.respin -o output.respout -e "
              "corrected.esp ".format(calc_dir_path) + input_charges_option +
              "-t charges.qout")
    return "charges.qout"


def _modify_ivary_list(resp_type, molecule, ivary_list1, ivary_list2,
                       inp_charges=None):
    result = []
    if inp_charges is None:
        if resp_type == 'd':
            raise ValueError("Modification of ivary list requested for "
                             "resp_type='d' but no input charges were given.")
        else:
            inp_charges = [None]*len(molecule)

    for atom, ivary1, ivary2, inp_charge in zip(molecule, ivary_list1,
                                                ivary_list2, inp_charges):
        if resp_type in ['h', 'u', 'd', 'e']:
            # Extract equivalence from the two default RESP inputs from
            # `respgen` program. This simple condition ensures that equivalence
            # (positive number) is picked over free fitting (zero), which is
            # picked over freezing charges (negative number). This is used by
            # the 'h_only', 'unrest' and 'dict' options of `run_resp` ('h', 'u'
            # and 'd') and also by the function `equivalence` ('e').
            ivary = max(ivary1, ivary2)
        else:
            raise NotImplementedError("Modification of ``ivary`` values not "
                                      "implemented for resp_type '{0}'."
                                      .format(resp_type))
        if resp_type == 'h':
            # Additionally freeze non-hydrogens
            ivary = ivary if atom.atomic_no == 1 else -1
        if resp_type == 'd':
            # Freeze atoms whose charges are specified in input
            ivary = ivary if inp_charge == unset_charge else -1
        result.append(ivary)
    return result


def _resp_two_stage(calc_dir_path, respin1_fn, respin2_fn, molecule,
                    check_ivary, read_input_charges):
    """Run the two-stage RESP but with potentially non-zero initial charges"""
    if check_ivary:
        print("\nTwo-stage RESP --- `ivary` values were not modified from the "
              "input `respin` files but you may want to inspect them "
              "nevertheless.\n\nSTAGE 1")

    ivary_list1, charge1, iuniq1 = _read_respin(respin1_fn,
                                                ref_molecule=molecule)
    # ivary_list1 used without modification. Modify the .respin1 file only to
    # ask to load initial charges if `read_input_charges` is True.
    _check_ivary(check_ivary, molecule, ivary_list1)
    _write_modified_respin('1', molecule, ivary_list1, charge1, iuniq1,
                           calc_dir_path + "input1.respin",
                           read_input_charges=read_input_charges)

    if check_ivary:
        print("\nSTAGE 2")
    # Although copying `.respin2` would suffice, _write_modified_respin is
    # called here as well for consistency. The respin file content could
    # potentially differ from that produced by `respgen` if its defaults change
    ivary_list2, charge2, iuniq2 = _read_respin(respin2_fn,
                                                ref_molecule=molecule)
    _check_ivary(check_ivary, molecule, ivary_list2)
    _write_modified_respin('2', molecule, ivary_list2, charge2, iuniq2,
                           calc_dir_path + "input2.respin",
                           read_input_charges=True)

    assert charge1 == charge2
    assert iuniq1 == iuniq2

    # Run resp
    input_charges_option = "-q input.qout " if read_input_charges else ""
    os.system("cd {0}; resp -i input1.respin -o output1.respout -e "
              "corrected.esp ".format(calc_dir_path) + input_charges_option +
              "-t charges1.qout -s esout1 -p punch1")
    os.system("cd {0}; resp -i input2.respin -o output2.respout -e "
              "corrected.esp -q charges1.qout -t charges2.qout -s esout2 "
              "-p punch2".format(calc_dir_path))
    return "charges2.qout"


def charges_from_dict(charge_dict, len_molecule):
    """Translate a charge dictionary to a list of charges

    If you only want to specify a few charges, it is more efficient to give
    them as a dictionary of the labels of the atoms that you want to specify,
    leaving out the others.

    Parameters
    ----------
    charge_dict : Dict[int: float]
        The keys are the labels of the atoms to be be specified, the values are
        the charge values. Note that if these charges are to be passed to
        ``run_resp`` and they are to be frozen, equivalence will not be
        invoked. Hence you must take care to assign equal values to equivalent
        atoms here. For example, to assign +0.1 to carbons and -0.2 to the
        nitrogen in  tetramethylammonium (NMe4), the input would be ``{17:
        -0.2, 1: 0.1, 5: 0.1, 9: 0.1, 13: 0.1}``
    len_molecule : int
        The number of atoms in the molecule.
    Returns
    -------
    List[float]
        A list of charges corresponding to the consecutive atoms in the
        molecule.
    """
    return [charge_dict[i+1] if i+1 in charge_dict else unset_charge for i in
            range(len_molecule)]


def equivalence(molecule, charge_type, input_dir, respin1_fn="",
                respin2_fn=""):
    """Average atomic charges type as per the equivalence from .respin files"""
    respin1, respin2 = _get_input_files(input_dir, respin1_fn, respin2_fn)
    ivary_list1, charge1, iuniq1 = _read_respin(respin1, ref_molecule=molecule)
    ivary_list2, charge2, iuniq2 = _read_respin(respin2, ref_molecule=molecule)
    assert charge1 == charge2
    assert iuniq1 == iuniq2
    ivary_list = _modify_ivary_list('e', molecule, ivary_list1, ivary_list2)
    # The algorithm isn't great. It seems to be correct and it's been verified
    # against two test cases. It can't, however, resolve more difficult
    # references, which should be fine for .respin files generated by
    # `respgen`. This can be fixed (see below) but needs to be done carefully.
    inp_charges = [atom.charges[charge_type] for atom in molecule]
    # A list of atoms which reference the given atom
    reffed_by = [[] for i in range(len(ivary_list))]
    for i, elem in enumerate(ivary_list):
        if elem:
            reffed_by[elem-1].append(i+1)
    # Check if any of the atoms is referenced by an atom which is referenced by
    # another atom.
    for refs in reffed_by:
        for ref in refs:
            if reffed_by[ref-1]:
                raise NotImplementedError(
                    "The `.respin` file contains more complicated references, "
                    "which cannot by resolved by the current implementation of"
                    " this function.")
                # TODO: To fix this deficiency, iterate over the `reffed_by`
                # list until this condition is False. Note: the implementation
                # should also be able to handle or at least detect circular
                # references.
    # Calculate the charges of atoms which are referened by other atoms
    result = []
    for i, refs in enumerate(reffed_by):
        if refs:
            charges_to_avg = [inp_charges[ref-1] for ref in refs]
            charges_to_avg.append(inp_charges[i])
            result.append(np.mean(charges_to_avg))
        else:
            result.append(None)
    # Fill the missing values by looking up the reference or the input charge,
    # depending on the ivary.
    new_result = []
    for i, elem in enumerate(result):
        if elem is None:
            if ivary_list[i] == 0:
                elem = inp_charges[i]
            else:
                elem = result[ivary_list[i]-1]
        new_result.append(elem)
    return new_result


def get_atom_signature(molecule, label):
    return molecule[label-1].identity + str(label)


def eval_one_charge_resp(charge, field, path, output_path, esp_fn,
                         molecule, vary_label, charge_dict, check_ivary,
                         optimization=False):
    # TODO: This function was written based on those optimizing ratios but
    # should be checked for overall code quality, e.g. if all arguments are
    # necessary or could be moved outside.
    if optimization:
        output_folder = ''.join(choice(ascii_lowercase) for _ in range(10))
    else:
        output_folder = "{0}{1:+.3f}".format(get_atom_signature(
            molecule, vary_label), charge)
    inp_charges = charges_from_dict(charge_dict(charge), len(molecule))
    updated_molecule = run_resp(
        path, output_path + output_folder, resp_type='dict',
        inp_charges=inp_charges, esp_fn=esp_fn, check_ivary=check_ivary)
    rrms_val = rms_and_rep(field, updated_molecule, 'resp')[1]
    return rrms_val


def eval_heavy_ratio(ratio, start_charges, field, path, output_path, esp_fn,
                     optimization=False, verbose=True):
    inp_charges = [charge*ratio for charge in start_charges]
    if optimization:
        # Generate folders with random names --- we don't care about the exact
        # steps of the optimization.
        output_folder = ''.join(choice(ascii_lowercase) for _ in range(10))
    else:
        output_folder = "ratio{0:+3f}".format(ratio)
    updated_molecule = run_resp(
        path, output_path + output_folder, resp_type='h_only',
        inp_charges=inp_charges, esp_fn=esp_fn, check_ivary=verbose)
    rrms_val = rms_and_rep(field, updated_molecule, 'resp')[1]

    if verbose > 1:
        print("\nHEAVY: RATIO: {0:.3f}, RRMS: {1:.3f}".format(ratio, rrms_val))
        for atom in updated_molecule:
            atom.print_with_charge('resp')

    return rrms_val


def eval_ratio(ratio, start_charges, molecule, field, verbose=True):
    inp_charges = [charge*ratio for charge in start_charges]
    charges._update_molecule_with_charges(molecule, inp_charges, 'temp')
    rrms_val = rms_and_rep(field, molecule, 'temp')[1]

    if verbose > 1:
        print("\nREGULAR: RATIO: {0:.3f}, RRMS: {1:.3f}".format(ratio,
                                                                rrms_val))
        for atom in molecule:
            atom.print_with_charge('temp')

    return rrms_val


def _find_bracket(x, y):
    """Find rough minimum location for ratio minimization"""
    assert len(x) == len(y)
    min_ind = y.index(min(y))
    # Check if the minimum value is not at the very edges of the interval:
    assert 0 < min_ind < len(x) - 1
    return x[min_ind-1: min_ind+2]


def _get_eval_func(eval_type):
    if eval_type == 'heavy':
        return eval_heavy_ratio
    elif eval_type == 'regular':
        return eval_ratio
    else:
        raise NotImplementedError("Optimizing the evaluation function given as"
                                  "is not implemented".format(eval_type))


def minimize_ratio(eval_type, ratio_values, result_list, eval_func_args):
    eval_func = _get_eval_func(eval_type)
    # eval_func_args should not contain verbosity information.
    # Add False for verbosity. Conversion to tuple proved necessary:
    eval_func_args = tuple(list(eval_func_args) + [False])
    bracket = _find_bracket(ratio_values, result_list)
    tol = 1e-6/min(result_list)
    minimized = minimize_scalar(eval_func, bracket=bracket,
                                tol=tol, args=eval_func_args)
    if not minimized.success:
        raise ValueError(
            "Minimization of {0} ratio failed. The message from `scipy."
            "optimize.minimize_scalar` is '{1}'".format(eval_type,
                                                        minimized.message))
    min_ratio, min_ratio_rrms = minimized.x, minimized.fun
    print("\nFOUND optimal {0} ratio: {1:.4f} with RRMS of {2:6f}\n".format(
          eval_type, min_ratio, min_ratio_rrms))
    return min_ratio, min_ratio_rrms


def find_flex(target_val, charge_values, result_list, eval_func_args):
    eval_func = lambda charge: eval_one_charge_resp(
        charge, *eval_func_args, False, True) - target_val
    min_ind = result_list.index(min(result_list))
    solution1 = brentq(eval_func, charge_values[0], charge_values[min_ind],
                       xtol=1e-5)
    solution2 = brentq(eval_func, charge_values[min_ind], charge_values[-1],
                       xtol=1e-5)
    return solution1, solution2


def eval_ratios(eval_type, ratio_limits, start_charges, sampling_num,
                indicator_label, eval_func_args, first_verbose=True):
    # eval_func_args should not contain verbosity information.
    indicator_charge = []
    result = []
    ratio_values = np.linspace(*ratio_limits, num=sampling_num)
    eval_func = _get_eval_func(eval_type)

    for ratio in ratio_values:
        indicator_charge.append(ratio*start_charges[indicator_label-1])
        rrms_val = eval_func(ratio, start_charges, *eval_func_args,
                             verbose=first_verbose)
        first_verbose = False
        result.append(rrms_val)

    return result, indicator_charge, ratio_values
