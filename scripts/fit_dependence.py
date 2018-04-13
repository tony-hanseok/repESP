#!/usr/bin/env python3

from repESP import resp, resp_helpers, rep_esp, charges
from repESP.field_comparison import difference, rms_and_rep
from repESP.resp import get_atom_signature

from numpy import linspace, meshgrid

import resp_parser

import argparse
import os
import sys
import shutil


help_description = """
    Investigate the dependence of the ESP fit on the charge on one or two atoms
    """

parser = argparse.ArgumentParser(
    parents=[resp_parser.parser],
    description=help_description,
    formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument("esp_file",
                    help=resp_parser.esp_file_help,
                    metavar="FILENAME")

parser.add_argument("--monitor",
                    help="""labels of atoms which charges are to be monitored
                    while the charge on atom1 (and optionally atom2) are varied""",
                    type=int, nargs="*", metavar="LABELS", default=[])

atom1_group = parser.add_argument_group(
    title="options regarding the first varied atom",
    description="Charge on this atom will be varied"
)

atom1_group.add_argument(
    "atom1",
    help="""label of the first atom which charge is to be varied""",
    type=int,
    metavar="LABEL"
)

atom1_group.add_argument(
    "--equivalent1",
    help="""If in the molecule there are atoms equivalent to the atom1, specify
    their labels. This ensures that the atoms cannot vary independently.""",
    type=int,
    nargs="*",
    metavar="LABELS",
    default=[]
)

atom1_group.add_argument(
    "--limits1",
    help="""range of atom1 charge values to be sampled""",
    nargs=2,
    type=float,
    default=(-1, 1),
    metavar=("LOWER", "UPPER")
)

atom1_group.add_argument(
    "--sampling1",
    help="""number of data points to be sampled for atom1 charges""",
    type=float,
    default=11,
    metavar="POINTS"
)

atom2_group = parser.add_argument_group(
    title="options regarding the second varied atom",
    description="Optionally the charge on another atom can be simultanously varied."
)

atom2_group.add_argument(
    "--atom2",
    help="""label of the second atom which charge is to be varied""",
    type=int,
    metavar="LABEL"
)

atom2_group.add_argument(
    "--equivalent2",
    help="""If in the molecule there are atoms equivalent to the atom1, specify
        their labels. This ensures that the atoms cannot vary independently.""",
    type=int,
    nargs="*",
    metavar="LABELS",
    default=[]
)

atom2_group.add_argument(
    "--limits2",
    help="""range of atom2 charge values to be sampled""",
    nargs=2,
    type=float,
    default=(-1, 1),
    metavar=("LOWER", "UPPER")
)

atom2_group.add_argument(
    "--sampling2",
    help="""number of data points to be sampled for atom2 charges""",
    type=float,
    default=11,
    metavar="POINTS"
)

args = parser.parse_args()

input_esp = args.respin_location + "/" + args.esp_file

temp_dir = "fit-dependence_temp_dir-dont_remove/"

if os.path.exists(temp_dir):
    raise FileExistsError("Output directory exists: " + temp_dir)

os.mkdir(temp_dir)

# Read the .esp file
info_from_esp = resp_helpers.G09_esp(input_esp)
# Write the .esp file in the correct format expected by the `resp` program
info_from_esp.field.write_to_file(temp_dir + "corrected.esp", info_from_esp.molecule)


def interpret(molecule, charge_dict, vary_label1, vary_label2=None):
    if vary_label2 is None:
        dictio = charge_dict(1)  # Example number to get the dict
    else:
        dictio = charge_dict(1, 2)  # Example numbers to get the dict
    print("\nCharges on these atoms will be varied:")
    for vary_label in vary_label1, vary_label2:
        if vary_label is None:
            break
        print('*', molecule[vary_label-1])
        equiv = [label for label in dictio if
                 dictio[label] == dictio[vary_label] and label != vary_label]
        if equiv:
            print("  with the following atoms equivalenced to it:")
            for equiv_label in sorted(equiv):
                print("  -", molecule[equiv_label-1])
    print("\nSee below for equivalence information of other atoms.")


def get_monitored(molecule, labels):
    return [atom.charges['resp'] for i, atom in enumerate(molecule) if i + 1 in labels]


def vary_one_atom():

    charge_dict = lambda x: {a: x for a in args.equivalent1 + [args.atom1]}
    interpret(info_from_esp.molecule, charge_dict, args.atom1)

    charges = linspace(args.limits1[0], args.limits1[1], num=args.sampling1)

    result = []

    for i, charge in enumerate(charges):

        inp_charges = resp.charges_from_dict(
            charge_dict(charge),
            len(info_from_esp.molecule)
        )

        _molecule = resp.run_resp(
            args.respin_location,
            temp_dir + "{0}{1:+.3f}".format(
                get_atom_signature(info_from_esp.molecule, args.atom1), charge,
            ),
            resp_type='dict',
            inp_charges=inp_charges,
            esp_fn=args.esp_file,
            check_ivary=i==0  # Only for the first iteration
        )

        rms, rrms, _ = rms_and_rep(info_from_esp.field, _molecule, 'resp')

        sys.stdout.write("\rSampling progress: {0:.2f} %".format(
            100*(i+1)/args.sampling1))
        sys.stdout.flush()

        result.append([
            charge,
            *get_monitored(_molecule, args.monitor),
            rms,
            rrms
        ])

    return result
