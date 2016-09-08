import numpy as np
from operator import attrgetter
from scipy.ndimage.morphology import distance_transform_edt as scipy_edt
from scipy.spatial.distance import euclidean
import glob
import os
import sys

# http://www.gaussian.com/g_tech/g_ur/k_constants.htm
angstrom_per_bohr = 0.5291772086
AXES = ['x', 'y', 'z']


class GridError(Exception):
    pass


class InputFormatError(Exception):
    pass


def _check_for_nans(values):
    try:
        values = values.flat
    except AttributeError:
        pass
    # http://stackoverflow.com/a/6736970
    if np.isnan(np.sum(values)):
        raise InputFormatError("Values contain NANs!")


class Cube(object):

    title_to_type = {
        ' Electrostatic pot': 'esp',
        ' Electron density ': 'ed',
        # Cube file generated by the ``bader`` program from Henkelman's group
        ' Bader charge': 'bader',
        }

    def __init__(self, cube_fn, coords_in_bohr=True):
        self.cube_fn = cube_fn
        with open(cube_fn, 'r') as f:

            self.gaussian_input = f.readline().rstrip('\n')
            self.title = f.readline().rstrip('\n')

            try:
                self.cube_type = Cube.title_to_type[self.title[:18]]
            except KeyError:
                self.cube_type = "unrecognized"
                # TODO: Cubes created by this program are currently not
                # recognized. When fixing this look for another use of the word
                # 'unrecognized' in this file.
                # raise NotImplementedError(
                #         "Cube title '" + self.title + "' is not associated "
                #         "with a known cube type.")

            line = f.readline().split()
            if len(line) == 5:
                self.atom_count, *origin_coords, nval = line
            elif len(line) == 4 and self.cube_type == 'bader':
                self.atom_count, *origin_coords = line
                nval = 1
            else:
                raise InputFormatError(
                    "Cube file incorrectly formatted! Expected five fields "
                    "(atom count, 3*origin coordinates, NVal) on line 3, found"
                    " {0}.".format(len(line)))

            if float(nval) != 1:
                raise GridError('NVal in the cube is different than 1. Not '
                                'sure what it means in practice.')
            self.atom_count = int(self.atom_count)

            grid = Grid([f.readline().split() for i in range(3)],
                        coords_in_bohr)
            grid.origin_coords = [float(coord) for coord in origin_coords]
            if coords_in_bohr:
                grid.origin_coords = [angstrom_per_bohr*coord for coord in
                                      grid.origin_coords]

            self.molecule = Molecule(self)
            # The atoms will be added to the Molecule in the order of
            # occurrence in the input, which is assumed to correspond to
            # Gaussian labels.
            for label in range(self.atom_count):
                atom_temp = f.readline().split()
                for index in range(4):
                    atom_temp[index+1] = float(atom_temp[index+1])

                new_atom = Atom(int(label)+1, int(atom_temp[0]), atom_temp[2:],
                                coords_in_bohr)
                new_atom.charges['cube'] = atom_temp[1]
                self.molecule.append(new_atom)

            # TODO: this may be unfeasible for very large cubes
            field = f.read().split()

        self.field = GridField(Cube.field_from_raw(field, grid), grid,
                               self.cube_type, 'input')

    @staticmethod
    def field_from_raw(raw_field, grid):
        field = np.array(list(map(float, raw_field)))
        if len(field) != np.prod(grid.points_on_axes):
            raise GridError('The number of points in the cube {0} is not equal'
                            ' to the product of number of points in the XYZ '
                            'directions given in the cube header: {1}.'
                            .format(len(field), grid.points_on_axes))

        field.resize(grid.points_on_axes)
        return field


class Atom(object):

    # http://www.science.co.il/PTelements.asp
    # TODO: this should be handled by a library
    periodic = [('H', 'Hydrogen'),
                ('He', 'Helium'),
                ('Li', 'Lithium'),
                ('Be', 'Beryllium'),
                ('B', 'Boron'),
                ('C', 'Carbon'),
                ('N', 'Nitrogen'),
                ('O', 'Oxygen'),
                ('F', 'Fluorine'),
                ('Ne', 'Neon'),
                ('Na', 'Sodium'),
                ('Mg', 'Magnesium'),
                ('Al', 'Aluminum'),
                ('Si', 'Silicon'),
                ('P', 'Phosphorus'),
                ('S', 'Sulfur'),
                ('Cl', 'Chlorine'),
                ('Ar', 'Argon'),
                ('XX', 'Unrecognized')]

    # Inverse look-up
    inv_periodic = {v[0]: i+1 for i, v in enumerate(periodic)}

    def __init__(self, label, atomic_no, coords=None, coords_in_bohr=None):
        self.label = label
        self.atomic_no = atomic_no
        try:
            self.identity = Atom.periodic[atomic_no-1][0]
        except IndexError:
            print('WARNING: Element of atomic number {0} not implemented. '
                  'Setting its identity to atomic number'.format(atomic_no))
            self.identity = str(atomic_no)

        self.charges = {}
        self.coords = coords
        if coords is not None:
            if coords_in_bohr is None:
                raise ValueError("When creating an Atom with coordinates, the "
                                 "units must be specified through the "
                                 "`coords_in_bohr` parameter.")
            if coords_in_bohr:
                self.coords = [angstrom_per_bohr*coord for coord in coords]

    def print_with_charge(self, charge_type, f=sys.stdout):
        print(self, ', charge: {0: .4f}'.format(self.charges[charge_type]),
              sep='', file=f)

    def __str__(self):
        return 'Atom {0:2}:  {1:2}'.format(self.label, self.identity)

    def __repr__(self):
        return str(self)

    def __eq__(self, other):
        result = self.atomic_no == other.atomic_no
        if self.coords is not None and other.coords is not None:
            result = result and self.coords == other.coords
        return result


class Molecule(list):
    """A list of atoms with extra functionalities."""

    def __init__(self, parent_cube, *args):
        list.__init__(self, *args)
        self.parent_cube = parent_cube

    def verbose_compare(self, other):
        if self == other:
            print("The molecules are the same.")
            return
        # Otherwise:
        print("The molecules differ at the following atoms:")
        for atom, other_atom in zip(self, other):
            if atom != other_atom:
                print("{0} != {1}".format(atom, other_atom))
        if len(self) != len(other):
            which = self if len(self) > len(other) else other
            which_str = 'first' if len(self) > len(other) else 'second'

            print("The {0} molecule has {1} more atoms:".format(
                which_str, abs(len(other) - len(self))))
            for atom in which[min(len(self), len(other)):]:
                print(atom)

    def extract_qtaim_basins(self, grid, path):
        """Extract QTAIM basins from Henkelman group's ``bader`` program

        The ``bader`` command needed to generate input cube files is::

            bader -p all_atom -vac off density.cube

        Assigning low density points to vacuum needs to be switched off in
        order to allow the basins to extend to infinity.

        This method returns a field with atomic labels indicating which basin
        each point belongs to.
        """
        output_files = glob.glob(path + 'BvAt*.cube')
        expected = [path + 'BvAt{0:04}.cube'.format(i+1) for i in
                    range(len(self))]

        if sorted(output_files) != expected:
            if len(output_files) == 0:
                msg = "No ``bader`` output cube files found!"
            else:
                for output_file, expected_file in zip(output_files, expected):
                    if output_file != expected_file:
                        msg += "Missing expected ``bader`` output cube file: "
                        msg += os.path.basename(expected)
                        break

            raise InputFormatError(msg + " To generate the files use the "
                                   "command: ``bader -p all_atom -vac off "
                                   "density.cube``")

        cubes = [Cube(expected_file) for expected_file in expected]
        # Compare grids with that provided. TODO: Would be better to use the
        # function field_comparison._check_grids, but can't import that module
        # here and won't be able to pass a special message. All that requires
        # some refactoring but is a sensible thing to do.
        for i, cube in enumerate(cubes):
            if cube.field.grid != grid:
                raise GridError("The grid of `bader' cube number {0} is "
                                "different from that of the molecule "
                                "requesting extraction.".format(i+1))

        result = []
        # Iterate all the cubes element-wise and produce a field with atomic
        # labels indicating which basin each point belongs to.
        # (This probably isn't the numpy way of doing this. It operates on
        # iterators though, so should be memory efficient.)
        for point in zip(*[cube.field.values.flat for cube in cubes]):
            point_bool = [True if elem else False for elem in point]
            if sum(point_bool) == 0:
                raise InputFormatError("Found point not assigned to any atom "
                                       "by the ``bader`` program. Maybe the "
                                       "``-vac off`` option was not set?")
            elif sum(point_bool) > 1:
                raise InputFormatError("Found point assigned to many atoms "
                                       "by the ``bader`` program. Possible "
                                       "numerical inconsistency in algorithm.")
            result.append(point_bool.index(True)+1)

        result = np.array(result)
        result.resize(self.parent_cube.field.grid.points_on_axes)
        return GridField(result, self.parent_cube.field.grid, 'parent_atom',
                         ['qtaim'])


class Field(object):

    def __init__(self, values, field_type, field_info, check_nans):
        self.check_nans = check_nans
        self.values = values
        self.field_type = field_type
        self.field_info = field_info

    def __setattr__(self, name, value):
        if name == 'values' and self.check_nans:
            _check_for_nans(value)
        super().__setattr__(name, value)

    def lookup_name(self):
        """Return free-form name

        The main purpose will probably be labelling axes when plotting.
        """
        if self.field_type in ['esp', 'ed']:
            if self.field_type == 'esp':
                result = "ESP value"
            elif self.field_type == 'ed':
                result = "ED value"
            if self.field_info[0] == 'input':
                result += " from input cube file"

        elif self.field_type == 'rep_esp':
            result = "Reproduced ESP value"
            if self.field_info[0]:
                result += " from {0} charges".format(self.field_info[0]
                                                     .upper())

        elif self.field_type == 'dist':
            result = "Distance"
            if self.field_info[0] == 'ed':
                result += " from ED isosurface {0}".format(self.field_info[1])
            elif self.field_info[0] == 'Voronoi':
                result += " from closest atom"
            elif self.field_info[0] == 'Voronoi':
                # This is not currently implemented
                result += " from QTAIM atom"

        elif self.field_type == 'diff':
            result = "difference"
            if 'abs' in self.field_info[0]:
                result += 'absolute'
            if 'rel' in self.field_info[0]:
                result += 'relative'
            result = result.capitalize()
            if len(self.field_info[1]) == 2:
                result += " between {0} and\n {1}".format(*self.field_info[1])

        elif self.field_type == 'parent_atom':
            result = "Parent atom"
            if self.field_info[0] == 'Voronoi':
                result += "of Voronoi basin"
            elif self.field_info[0] == 'qtaim':
                result += "of QTAIM basin"
        elif self.field_type == "unrecognized":
            result = "Unrecognized"
        else:
            raise NotImplementedError("Free-form name not implemented for "
                                      "Field of type '{0}' and info '{1}'"
                                      .format(self.field_type,
                                              self.field_info))
        return result


class GridField(Field):

    def __init__(self, values, grid, field_type, field_info=None,
                 check_nans=True):
        self.grid = grid
        super().__init__(values, field_type, field_info, check_nans)

    def distance_transform(self, isovalue):
        """This should only be applied to the electron density cube."""

        if self.field_type != 'ed':
            print("WARNING: Distance transform should only be applied to "
                  "electron density fields, attempted on field type: '{0}'."
                  .format(self.field_type))

        if not self.grid.aligned_to_coord:
            raise GridError('Distance transform not implemented for grid not '
                            'aligned with the coordinate system.')

        # Select isosurface and its interior as a 3D solid of 0s.
        select_iso = lambda x: 1 if x < isovalue else 0
        field = np.vectorize(select_iso)(self.values)
        dist = scipy_edt(field, sampling=self.grid.dir_intervals)
        return GridField(dist, self.grid, 'dist', ['ed', isovalue])

    def write_cube(self, output_fn, molecule, charge_type=None,
                   write_coords_in_bohr=True):
        """Write the field as a Gaussian cube file.

        Raises FileExistsError when the file exists.
        """
        with open(output_fn, 'x') as f:
            f.write(' Cube file generated by repESP.\n')
            f.write(' Cube file for field of type {0}.\n'.format(
                self.field_type))
            origin_coords = self.grid.origin_coords
            if write_coords_in_bohr:
                origin_coords = [elem/angstrom_per_bohr for elem in
                                 origin_coords]
            f.write(' {0:4}   {1: .6f}   {2: .6f}   {3: .6f}    1\n'.format(
                len(molecule), *origin_coords))
            for axis in self.grid.axes:
                axis_intervals = axis.intervals
                if write_coords_in_bohr:
                    axis_intervals = [elem/angstrom_per_bohr for elem in
                                      axis_intervals]
                f.write(' {0:4}   {1: .6f}   {2: .6f}   {3: .6f}\n'.format(
                    axis.point_count, *axis_intervals))
            for atom in molecule:
                if charge_type is None:
                    charge = atom.atomic_no
                else:
                    charge = atom.charges[charge_type]
                atom_coords = atom.coords
                if write_coords_in_bohr:
                    atom_coords = [coord/angstrom_per_bohr for coord in
                                   atom_coords]
                f.write(' {0:4}   {1: .6f}   {2: .6f}   {3: .6f}   {4: .6f}\n'
                        .format(atom.atomic_no, charge, *atom_coords))
            i = 1
            for value in self.values.flatten():
                f.write(' {0: .5E}'.format(value))
                if not i % 6:
                    f.write('\n')
                if not i % self.grid.axes[2].point_count:
                    f.write('\n')
                    i = 1
                else:
                    i += 1


class Grid(object):

    def __init__(self, grid_input, coords_in_bohr):

        self.origin_coords = None

        if np.shape(grid_input) != (3, 4):
            raise GridError('Incorrect grid formatting. Expected a list of '
                            'shape 3x4, instead got: ' + str(grid_input))

        self.axes = [GridAxis(label) for label in AXES]
        self.aligned_to_coord = True

        for axis_number, input_axis in enumerate(grid_input):
            aligned_to_axis = self._add_axis(axis_number, input_axis,
                                             coords_in_bohr)
            # All axes must fulfil this condition, hence the logic
            self.aligned_to_coord = self.aligned_to_coord and aligned_to_axis

        self.dir_intervals = []
        if self.aligned_to_coord:
            for axis in range(3):
                self.dir_intervals.append(self.axes[axis].dir_interval)
        else:
            raise GridError('The cube is not aligned with coordinate system.')

        self.points_on_axes = [axis.point_count for axis in self.axes]

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def _add_axis(self, axis_number, input_axis, coords_in_bohr):
        axis_to_set = self.axes[axis_number]
        axis_to_set.set_point_count(input_axis.pop(0))
        return axis_to_set.set_intervals(input_axis, coords_in_bohr)


class GridAxis(object):

    def __init__(self, label):
        self.label = label
        self.point_count = None
        self.intervals = []  # xyz
        self.dir_interval = None  # Interval in its 'own' direction

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def set_point_count(self, point_count):

        if int(point_count) != float(point_count):
            raise GridError('Number of points in direction {0} is not an '
                            'integer: {1}'.format(self.label, point_count))

        self.point_count = int(point_count)

    def set_intervals(self, intervals, coords_in_bohr):

        aligned_to_coord_axis = True

        for direction, interval in enumerate(intervals):
            interval = float(interval)
            if coords_in_bohr:
                interval *= angstrom_per_bohr
            self.intervals.append(interval)
            if AXES[direction] == self.label:
                self.dir_interval = interval
            elif interval != 0:
                aligned_to_coord_axis = False

        if not aligned_to_coord_axis:
            print('INFO: Cube axis {0} is not aligned to its coordinate'
                  ' axis: The intervals are: {1}'.format(self.label,
                                                         intervals))

        return aligned_to_coord_axis
