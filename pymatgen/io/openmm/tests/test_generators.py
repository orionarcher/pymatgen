# base python
import pytest

# cheminformatics
import numpy as np
import parmed

# openff
import openff.toolkit.topology
from openff.toolkit.typing.engines import smirnoff

# openmm
import openmm
from openmm.unit import elementary_charge
from openmm import NonbondedForce

# pymatgen
import pymatgen

from pymatgen.io.openmm.sets import OpenMMSet
from pymatgen.io.openmm.generators import OpenMMSolutionGen

from pymatgen.io.openmm.tests.datafiles import (
    CCO_xyz,
    CCO_charges,
    FEC_r_xyz,
    FEC_s_xyz,
    FEC_charges,
    PF6_xyz,
    PF6_charges,
    Li_charges,
    Li_xyz,
)

__author__ = "Orion Cohen, Ryan Kingsbury"
__version__ = "1.0"
__maintainer__ = "Orion Cohen"
__email__ = "orion@lbl.gov"
__date__ = "Nov 2021"


class TestOpenMMSolutionGen:
    def test_smile_to_molecule(self):
        mol = OpenMMSolutionGen._smile_to_molecule("CCO")
        assert isinstance(mol, pymatgen.core.structure.Molecule)
        assert len(mol.sites) == 9

    def test_smile_to_parmed_structure(self):
        struct1 = OpenMMSolutionGen._smile_to_parmed_structure("CCO")
        assert isinstance(struct1, parmed.Structure)
        assert len(struct1.atoms) == 9
        assert len(struct1.residues) == 1
        assert len(struct1.bonds) == 8
        struct2 = OpenMMSolutionGen._smile_to_parmed_structure("O")
        assert len(struct2.atoms) == 3
        assert len(struct2.residues) == 1
        assert len(struct2.bonds) == 2
        struct3 = OpenMMSolutionGen._smile_to_parmed_structure("O=C1OC[C@H](F)O1")
        assert len(struct3.atoms) == 10
        assert len(struct3.residues) == 1
        assert len(struct3.bonds) == 10

    def test_get_openmm_topology(self):
        topology = OpenMMSolutionGen._get_openmm_topology({"O": 200, "CCO": 20})
        assert isinstance(topology, openmm.app.Topology)
        assert topology.getNumAtoms() == 780
        assert topology.getNumResidues() == 220
        assert topology.getNumBonds() == 560
        ethanol_smile = "CCO"
        fec_smile = "O=C1OC[C@H](F)O1"
        topology = OpenMMSolutionGen._get_openmm_topology({ethanol_smile: 50, fec_smile: 50})
        assert topology.getNumAtoms() == 950

    def test_get_box(self):
        box = OpenMMSolutionGen.get_box({"O": 200, "CCO": 20}, 1)
        assert isinstance(box, list)
        assert len(box) == 6
        np.testing.assert_allclose(box[0:3], 0, 2)
        np.testing.assert_allclose(box[3:6], 19.59, 2)

    def test_get_coordinates(self):
        coordinates = OpenMMSolutionGen._get_coordinates({"O": 200, "CCO": 20}, [0, 0, 0, 19.59, 19.59, 19.59], 1)
        assert isinstance(coordinates, np.ndarray)
        assert len(coordinates) == 780
        assert np.min(coordinates) > -0.2
        assert np.max(coordinates) < 19.8
        assert coordinates.size == 780 * 3

    @pytest.mark.parametrize(
        "xyz_path, n_atoms, n_bonds",
        [
            (CCO_xyz, 9, 8),
            (FEC_r_xyz, 10, 10),
            (FEC_s_xyz, 10, 10),
            (PF6_xyz, 7, 6),
        ],
    )
    def test_infer_openff_mol(self, xyz_path, n_atoms, n_bonds):
        mol = pymatgen.core.Molecule.from_file(xyz_path)
        openff_mol = OpenMMSolutionGen._infer_openff_mol(mol)
        assert isinstance(openff_mol, openff.toolkit.topology.Molecule)
        assert openff_mol.n_atoms == n_atoms
        assert openff_mol.n_bonds == n_bonds

    @pytest.mark.parametrize(
        "xyz_path, smile, map_values",
        [
            (CCO_xyz, "CCO", [0, 1, 2, 3, 4, 5, 6, 7, 8]),
            (FEC_r_xyz, "O=C1OC[C@@H](F)O1", [0, 1, 2, 3, 4, 6, 7, 9, 8, 5]),
            (FEC_s_xyz, "O=C1OC[C@H](F)O1", [0, 1, 2, 3, 4, 6, 7, 9, 8, 5]),
            (PF6_xyz, "F[P-](F)(F)(F)(F)F", [1, 0, 2, 3, 4, 5, 6]),
        ],
    )
    def test_get_atom_map(self, xyz_path, smile, map_values):
        mol = pymatgen.core.Molecule.from_file(xyz_path)
        inferred_mol = OpenMMSolutionGen._infer_openff_mol(mol)
        openff_mol = openff.toolkit.topology.Molecule.from_smiles(smile)
        isomorphic, atom_map = OpenMMSolutionGen._get_atom_map(inferred_mol, openff_mol)
        assert isomorphic
        assert map_values == list(atom_map.values())

    @pytest.mark.parametrize(
        "charges_path, smile, atom_values",
        [
            (Li_charges, "[Li+]", [0]),
            (CCO_charges, "CCO", [0, 1, 2, 3, 4, 5, 6, 7, 8]),
            (FEC_charges, "O=C1OC[C@@H](F)O1", [0, 1, 2, 3, 4, 9, 5, 6, 7, 8]),
            (FEC_charges, "O=C1OC[C@H](F)O1", [0, 1, 2, 3, 4, 9, 5, 6, 7, 8]),
            (PF6_charges, "F[P-](F)(F)(F)(F)F", [1, 0, 2, 3, 4, 5, 6]),
        ],
    )
    def test_add_mol_charges_to_forcefield(self, charges_path, smile, atom_values):
        charges = np.load(charges_path)
        openff_mol = openff.toolkit.topology.Molecule.from_smiles(smile)
        atom_map = {i: j for i, j in enumerate(atom_values)}  # this saves some space
        mapped_charges = np.array([charges[atom_map[i]] for i in range(len(charges))])
        openff_mol.partial_charges = mapped_charges * elementary_charge
        forcefield = smirnoff.ForceField("openff_unconstrained-2.0.0.offxml")
        OpenMMSolutionGen._add_mol_charges_to_forcefield(forcefield, openff_mol)
        topology = openff_mol.to_topology()
        system = forcefield.create_openmm_system(topology)
        for force in system.getForces():
            if type(force) == NonbondedForce:
                for i in range(force.getNumParticles()):
                    assert force.getParticleParameters(i)[0]._value == mapped_charges[i]

    def test_add_partial_charges_to_forcefield(self):
        # set up partial charges
        ethanol_mol = pymatgen.core.Molecule.from_file(CCO_xyz)
        fec_mol = pymatgen.core.Molecule.from_file(FEC_s_xyz)
        ethanol_charges = np.load(CCO_charges)
        fec_charges = np.load(FEC_charges)
        partial_charges = [(ethanol_mol, ethanol_charges), (fec_mol, fec_charges)]
        # set up force field
        ethanol_smile = "CCO"
        fec_smile = "O=C1OC[C@H](F)O1"
        openff_forcefield = smirnoff.ForceField("openff_unconstrained-2.0.0.offxml")
        openff_forcefield = OpenMMSolutionGen._add_partial_charges_to_forcefield(
            openff_forcefield,
            ["CCO", "O=C1OC[C@H](F)O1"],
            {},
            partial_charges,
        )
        openff_forcefield_scaled = smirnoff.ForceField("openff_unconstrained-2.0.0.offxml")
        openff_forcefield_scaled = OpenMMSolutionGen._add_partial_charges_to_forcefield(
            openff_forcefield_scaled,
            ["CCO", "O=C1OC[C@H](F)O1"],
            {"CCO": 0.9, "O=C1OC[C@H](F)O1": 0.9},
            partial_charges,
        )
        # construct a System to make testing easier
        openff_mols = [openff.toolkit.topology.Molecule.from_smiles(smile) for smile in [ethanol_smile, fec_smile]]
        topology = OpenMMSolutionGen._get_openmm_topology({ethanol_smile: 50, fec_smile: 50})
        openff_topology = openff.toolkit.topology.Topology.from_openmm(topology, openff_mols)
        system = openff_forcefield.create_openmm_system(openff_topology)
        system_scaled = openff_forcefield_scaled.create_openmm_system(openff_topology)
        # ensure that all forces are from our assigned force field
        # this does not ensure correct ordering, as we already test that with
        # other methods
        fec_charges_reordered = fec_charges[[0, 1, 2, 3, 4, 6, 7, 8, 9, 5]]
        full_partial_array = np.append(np.tile(ethanol_charges, 50), np.tile(fec_charges_reordered, 50))
        for force in system.getForces():
            if type(force) == NonbondedForce:
                charge_array = np.zeros(force.getNumParticles())
                for i in range(len(charge_array)):
                    charge_array[i] = force.getParticleParameters(i)[0]._value
        np.testing.assert_allclose(full_partial_array, charge_array, atol=0.0001)
        for force in system_scaled.getForces():
            if type(force) == NonbondedForce:
                charge_array = np.zeros(force.getNumParticles())
                for i in range(len(charge_array)):
                    charge_array[i] = force.getParticleParameters(i)[0]._value
        np.testing.assert_allclose(full_partial_array * 0.9, charge_array, atol=0.0001)

    def test_parameterize_system(self):
        # TODO: add test here to see if I am adding charges?
        topology = OpenMMSolutionGen._get_openmm_topology({"O": 200, "CCO": 20})
        smile_strings = ["O", "CCO"]
        box = [0, 0, 0, 19.59, 19.59, 19.59]
        force_field = "Sage"
        system = OpenMMSolutionGen._parameterize_system(topology, smile_strings, box, force_field, {}, [])
        assert system.getNumParticles() == 780
        assert system.usesPeriodicBoundaryConditions()

    def test_get_input_set(self):
        generator = OpenMMSolutionGen(packmol_random_seed=1)
        input_set = generator.get_input_set({"O": 200, "CCO": 20}, density=1)
        assert isinstance(input_set, OpenMMSet)
        assert set(input_set.inputs.keys()) == {
            "topology.pdb",
            "system.xml",
            "integrator.xml",
            "state.xml",
        }
        assert input_set.validate()

    def test_get_input_set_w_charges(self):
        pf6_charge_array = np.load(PF6_charges)
        li_charge_array = np.load(Li_charges)
        generator = OpenMMSolutionGen(
            partial_charges=[(PF6_xyz, pf6_charge_array), (Li_xyz, li_charge_array)],
            partial_charge_scaling={"Li": 0.9, "PF6": 0.9},
            packmol_random_seed=1,
        )
        input_set = generator.get_input_set({"O": 200, "CCO": 20, "F[P-](F)(F)(F)(F)F": 10, "[Li+]": 10}, density=1)
        assert isinstance(input_set, OpenMMSet)
        assert set(input_set.inputs.keys()) == {
            "topology.pdb",
            "system.xml",
            "integrator.xml",
            "state.xml",
        }
        assert input_set.validate()
