# Running the scripts

TODO.
A description of the scripts and their parameters should be added.

# Producing input files for new molecules

Two molecules, methane and trimethylammonium, can be found in the data folder.
The files in their respective folders show the necessary input for the program.
Some of them, such as the `.sumviz` file and some of the `.log` files are optional if you don't need the partial charges which they contain.
The structure of the input data directory should align with that exemplified by the two molecules provided.

## `.log` files

The `.log` files contain the partial charges calculated by Gaussian.
All the `.log` files can be obtained by running Gaussian on the corresponding `.com` files
Example `.com` files are given for methane in its `prep` folder.
For new molecules you should follow roughly the following procedure:

* Create the parent directory for your molecule and the subdirectory `prep`, which should be your working directory.
* Optimize the structure and check for imaginary frequencies.
  Keep the checkpoint file.
* Using the examples in the `prep` subdirectory of methane, create a `.com` file with the desired instructions for Gaussian.
  You should use `Read=Check` to read the structure from a *copy* of the checkpoint file from the previous step.
* Move the output `.log` file to the parent directory of your molecule.
  For ESP charge methods, also move the resulting `.esp` file to the parent directory.

## QTAIM charges

Since the charges produced by the `bader` program were found to be inconsistent, it is advised that the `AIMAll` studio is used to generate the QTAIM charges.

* Generate the wavefunction (`.wfx`) file by running Gaussian on an input file derived from the methane example `methane_wfx.com`.
* From `AIMStudio` run AIMQB on the wavefunction with all the default settings.
* Move the resulting `.sumviz` file to the parent directory.
  You may keep all the other resultant files in your `prep` directory, preferably in a subfolder, e.g. `aim_output`.

## Cube files

To create electron density (ED) and electrostatic potential (ESP):

* Format the checkpoint file using `formchk`.
* Run `cubegen` for both cube files, e.g.:

		cubegen 1 Density=SCF methane.fchk methane_den.cub -2
		cubegen 1 Potential=SCF methane.fchk methane_esp.cub -2

The `SCF` option may not be relevant to the level of theory used in your calculation.
Refer to Gaussian's documentation for `cubegen` and the keyword `Density`.
Also, `cubegen` now has an option to calculate the ED cube using 'full density instead of frozen core', which may be desired but it's not clear whether such cube would be consistent with the ESP cube.
The last parameter specifies the point density of the cube grid, -2 corresponding to 'coarse'.

## QTAIM basins

The QTAIM basins should be generated by running the `bader` program of the Henkelman's group on the ED cube file.
Run:

	bader -p all_atom -vac off methane_den.cub

and move the generated `.cube` (sic) and `.dat` files to a new folder `bader` in your molecule directory.


## RESP input

First, create the `.ac` file using `antechamber`, which is freely available as part of `AmberTools`:

	antechamber -i g98.out -fi gout -o methane.ac -fo ac 

Then run `respgen`, which is also available as part of `AmberTools`:

	respgen -i sustiva.ac -o sustiva.respin1 -f resp1
	respgen -i sustiva.ac -o sustiva.respin2 -f resp2

## Running `resp` manually

The newest version of the `resp` program is available as a standalone and under a free licence.
To manually run `resp`, you need to generate the fitting grid for your molecule.
This is done in Gaussian 09 through IOp(6/50=1) and will generate an `.esp` file.
(Older versions of Gaussian do it in a different way, which is currently not supported.)
This procedure was included in the demonstration `.com` files for calculating MK and CHelpG charges.
However, the resulting `.esp` are in a different format than that expected by the `resp` program.
It can be translated by reading in the output file as a `resp_helpers.G09_esp` object and calling the `write_to_file` method of its `field` attribute.
A simple command line program may be provided in the future to make it easier.

The `resp` can be run, e.g. in its default 'two-stage' version, according to its instructions [online](http://upjv.q4md-forcefieldtools.org/RED/resp/).

# Creating reproducible results

Running the provided scripts on your molecule will generate a folder in your molecule's directory.
Make sure that you redirect (best using `tee`) the output of the script and then move it to the newly created output directory.
You should also append the git commit hash of the `repESP` program (later a program version may suffice).