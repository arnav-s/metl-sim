from Bio.PDB import PDBParser


def compare_pdbs(pdb_files):
    """
    Parse a list of PDB files, print their chain + residue identities,
    and find the differences between them.
    """
    parser = PDBParser(QUIET=True)
    structures = {}

    # Parse all PDB files
    for pdb in pdb_files:
        structure = parser.get_structure(pdb, pdb)
        # Collect residue identifiers for each structure
        residues = set()
        for model in structure:
            for chain in model:
                for residue in chain:
                    # residue id looks like (' ', 1, ' ')
                    residues.add((chain.id, residue.id[1], residue.resname))
        structures[pdb] = residues
        print(f"\n📄 {pdb} contains {len(residues)} residues")
        for chain_id, resnum, resname in sorted(residues):
            print(f"  Chain {chain_id}, Residue {resnum} ({resname})")

    # Find differences pairwise
    pdb_names = list(structures.keys())
    for i in range(len(pdb_names)):
        for j in range(i + 1, len(pdb_names)):
            pdb1, pdb2 = pdb_names[i], pdb_names[j]
            diff1 = structures[pdb1] - structures[pdb2]
            diff2 = structures[pdb2] - structures[pdb1]
            print(f"\n🔎 Differences between {pdb1} and {pdb2}:")
            if diff1:
                print(f"  Present in {pdb1} but not in {pdb2}: {diff1}")
            else:
                print(f"  No unique residues in {pdb1} compared to {pdb2}")
            if diff2:
                print(f"  Present in {pdb2} but not in {pdb1}: {diff2}")
            else:
                print(f"  No unique residues in {pdb2} compared to {pdb1}")

if __name__ == '__main__':
    compare_pdbs(["structure.pdb", "flags_relax_v3_structure_0001.pdb","flags_relax_v3_structure_0001_disable_design_false.pdb"])

