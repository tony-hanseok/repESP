import ipdb
from cube_helpers import Atom, Cube

esp_type_in_log = {
    ' Merz-Kollman atomic radii used.': 'mk',
    ' Francl (CHELP) atomic radii used.': 'chelp',
    ' Breneman (CHELPG) radii used.': 'chelpg',
    }

esp_charges = esp_type_in_log.values()


# First 8 characters of the line following charge output in various input files
charge_termination_line = {
    'sumviz': '--------',
    'log': (' Sum of ', ' =======')
    }


class InputFormatError(Exception):
    pass


def update_with_charges(charge_type, filename, molecule):
    """Update the molecule with charges

    Only charges calculated directly by Gaussian are currently supported. The
    charges should be given in a Gaussian output file (.log or .out). In the
    future, checkpoint and formatted checkpoint formats will be supported.

    Note that if Gaussian output file contains information about charges in
    more than one place, only the last one will be used. Also, the atom list is
    assumed to be in order.
    """
    if filename[-4:] in ['.log', '.out']:
        _get_charges(charge_type, filename, 'log', molecule)
    elif filename[-7:] == '.sumviz' and charge_type == 'aim':
        _get_charges('aim', filename, 'sumviz', molecule)
    elif filename[-4:] in ['.chk', '.fchk']:
        raise NotImplementedError('File extension {0} currently not supported.'
                                  .format(filename[-4]))
    else:
        raise NotImplementedError('File extension {0} is not supported.'
                                  .format(filename[-4]))


def _get_charges(charge_type, filename, input_type, molecule):
    """Update the molecule with charges."""
    with open(filename, 'r') as file_object:
        globals()['_goto_in_' + input_type](charge_type, file_object)
        charges = _get_charges_from_lines(charge_type, file_object,
                                          input_type, molecule)
        _update_molecule_with_charges(molecule, charges, charge_type)


def _goto_in_log(charge_type, file_object, occurence=-1):
    """Go to the selected occurence of input about charges in a log file.

    Occurence is the index to a list containing all occurences of the given
    charge type, so should be 0 for the first occurence and -1 for the last.
    Code based on: http://stackoverflow.com/a/620492
    """
    offset = 0
    result = []
    esp_types = []

    for line in file_object:
        offset += len(line)
        line = line.rstrip('\n')
        # All ESP charges are added here, as they cannot be distinguished just
        # by the header
        if line.rstrip() == _charge_section_header_in_log(charge_type):
            result.append(offset)
        # The information about the type of ESP charges is gathered separately
        if charge_type in esp_charges and line in esp_type_in_log:
            esp_types.append(esp_type_in_log[line])

    if charge_type in esp_charges:
        # Verify if all ESP charge output has been recognized correctly
        if len(esp_types) != len(result):
            raise InputFormatError('Information about the type of some '
                                   'ESP charges was not recognized.')
        # Filter only the requested ESP charge type
        result = [elem for i, elem in enumerate(result) if
                  esp_types[i] == charge_type]

    if not result:
        raise InputFormatError("Output about charge type '{0}' not found."
                               .format(charge_type))

    try:
        file_object.seek(result[occurence])
    except IndexError:
        raise IndexError(
            "Cannot find occurence '{0}' in a list of recognized pieces of "
            "output about charges, whose length is {1}.".format(occurence,
                                                                len(result)))

    # Skip unnecessary lines
    lines_count = 1
    if charge_type == 'nbo':
        lines_count = 5
    for counter in range(lines_count):
        file_object.readline()


def _goto_in_sumviz(charge_type, file_object):
    while file_object.readline().rstrip('\n') != 'Some Atomic Properties:':
        pass
    # Skip irrelevant lines
    for i in range(9):
        file_object.readline()


def _charge_section_header_in_log(charge_type):
    if charge_type == 'mulliken':
        return ' Mulliken charges:'
    elif charge_type in esp_charges:
        return ' ESP charges:'
    elif charge_type == 'nbo':
        return ' Summary of Natural Population Analysis:'
    else:
        raise NotImplementedError("Charge type '{0}' is not implemented."
                                  .format(charge_type))


def _update_molecule_with_charges(molecule, charges, charge_type):
    for atom, charge in zip(molecule, charges):
        atom.charges[charge_type] = charge


def _log_charge_line(line, charge_type):
    if charge_type == 'nbo':
        letter, label, charge, *other = line.split()
    else:
        label, letter, charge = line.split()
    label = int(label)
    charge = float(charge)
    return label, letter, charge


def _sumviz_charge_line(line, charge_type):
    letter_and_label, charge, *other = line.split()
    # These should actually be a regex for letters and numbers
    letter = letter_and_label[0]
    label = int(letter_and_label[1])
    charge = float(charge)
    return label, letter, charge


def _get_charges_from_lines(charge_type, file_object, input_type, molecule):
    """Extract charges from the charges section in output

    Parameters
    ----------
    file_object : File
        The file from which the charges are to be extracted. The file is
        expected to be set to the position of the start of charges section,
        e.g. with the _goto_in_log helper.
    input_type : str
        Currently implemented is reading lines from Gaussian ('log') and AIM
        ('sumviz') output files.
    molecule : Molecule
        The molecule to which the charges relate. Note that the molecule will
        not be updated with the charges, this must be done separately by the
        caller.

    Returns
    -------
    List[float]
        List of charges in order of occurence in output file.

    Raises
    ------
    NotImplementedError
        Raised when an unsupported input file type is requested.
    InputFormatError
        Raised when the order of atoms is not as expected from the Molecule or
        the length of the charges section is different than expected.

    """
    charges = []
    for i, atom in enumerate(molecule):
        try:
            # Input type-specific extraction performed by specialist function
            label, letter, charge = globals()[
                '_' + input_type + '_charge_line'](file_object.readline(),
                                                   charge_type)
        except KeyError:
            raise NotImplementedError(
                "Reading charges from an input file of type '{0} 'is not "
                "supported.".format(input_type))

        # Check if the labels are in order
        if label is not None and label != i + 1:
            raise InputFormatError(
                "Charge section is not given in order of Gaussian labels. This"
                " may be a feature of the program which generated the charges "
                "output but is not supported in this program.")
        # Check if the atom identities agree between atom list and input
        if letter != atom.identity:
            raise InputFormatError(
                'Atom {0} in atom list is given as {1} but input file '
                'expected {2}'.format(int(label)+1, atom.identity, letter))

        charges.append(charge)

    # Check if the atom list terminates after as many atoms as expected from
    # the Molecule object given
    next_line = file_object.readline()
    # Kludged, in fact charge_termination_line depends on both file and charge
    # types.
    if next_line[:8] not in charge_termination_line[input_type]:
        raise InputFormatError(
            "Expected end of charges ('{0}'), instead got: '{1}'".format(
                charge_termination_line[input_type], next_line[:8]))

    return charges
