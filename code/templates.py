""" Fills the template files for energize pipeline """
import os
from os.path import join
import shutil

import numpy as np

from utils import get_seq_from_pdb


def gen_res_selector_str(variant, index_type="1-based"):
    """ generates the ResidueIndexSelector string Rosetta scripts """
    resnums = []
    for mutation in variant.split(","):
        if index_type == "1-based":
            resnum_1_index = int(mutation[1:-1])
        elif index_type == "0-based":
            resnum_0_idx = int(mutation[1:-1])
            resnum_1_index = resnum_0_idx + 1
        else:
            raise ValueError("unrecognized index_type {}".format(index_type))
        resnums.append("{}A".format(resnum_1_index))
    resnum_str = ",".join(resnums)
    return resnum_str





def gen_resfile_str(template_dir, chain, variant, index_type="1-based"):
    """residue_number chain PIKAA replacement_AA"""

    mutation_strs = []
    for mutation in variant.split(","):
        if index_type == "1-based":
            resnum_1_index = int(mutation[1:-1])
        elif index_type == "0-based":
            resnum_0_idx = int(mutation[1:-1])
            resnum_1_index = resnum_0_idx + 1
        else:
            raise ValueError("unrecognized index_type {}".format(index_type))
        new_aa = mutation[-1]

        mutation_strs.append("{} {} PIKAA {}".format(resnum_1_index, chain, new_aa))

    # add new lines between mutation strs
    mutation_strs = "\n".join(mutation_strs)

    # load the templates
    template_fn = join(template_dir, "mutation_template.resfile")
    with open(template_fn, "r") as f:
        template_str = f.read()

    formatted_template = template_str.format(mutation_strs)

    return formatted_template



def mutate_str_xml(variant,chain,seq_length):
    aa_map = {
        "A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE", "G": "GLY",
        "H": "HIS", "I": "ILE", "K": "LYS", "L": "LEU", "M": "MET", "N": "ASN",
        "P": "PRO", "Q": "GLN", "R": "ARG", "S": "SER", "T": "THR", "V": "VAL",
        "W": "TRP", "Y": "TYR"
    }
    variants = variant.split(',')
    idxs = []
    mutate_residue_blocks = []
    protocols = []

    if variant!='_wt':
        resnum_str = gen_res_selector_str(variant)
        # print("resnum str: ",resnum_str)
        for i, v in enumerate(variants, 1):
            if len(v) < 3:
                raise ValueError(f"ERROR: length(variant) < 3 : {v}")
            parent_aa, residue_idx, new_aa = v[0], v[1:-1], v[-1]

            idxs.append(residue_idx + chain)
            mutate_residue_blocks.append(
                f'<MutateResidue name="mutant{i}" target="{residue_idx}{chain}" new_res="{aa_map[new_aa]}"/>')
            # mutate_residue_movers.append(f'<Add mover_name="mutant{i}"/>')
            protocols.append(f'<Add mover_name="mutant{i}"/>')

    else:
        # if the input is _wt then just add some more spaces, we don't mutate
        # or add in a mover
        # and we select all residues during the FAstRelax.
        protocols = [" ", " "]
        mutate_residue_blocks = [" ", " "]
        # we will only do chain A.
        resnum_str = ",".join([f"{str(i + 1)}A" for i in np.arange(seq_length)])
        # print("resnum str: ",resnum_str)





    return resnum_str,protocols,mutate_residue_blocks



def fill_templates(template_dir, chain, variant, rosetta_hparams,out_dir,pdb_fn):

    # the mutate xml no longer has any argument that need to be filled in, so just copy the template
    # todo: this could be done in prep_working_dir in energize.py instead, that's where other files
    #   that are unchanged are copied from the template dir to the working dir
    # shutil.copy(join(template_dir, "mutate_template.xml"), join(out_dir, "mutate.xml"))

    seq_length=len(get_seq_from_pdb(pdb_fn))

    resnum_str, protocols, mutate_residue_blocks  = mutate_str_xml(variant,chain,seq_length)

    rosetta_hparams_str = {k: str(v) for k, v in rosetta_hparams.items()}


    # now fill out the templates
    template_fns = ["relax_temp.xml", "flags_relax_temp"]
    output_fns = ["relax.xml","flags_relax"]

    for template_fn,output_fn in zip(template_fns,output_fns):
        # load the template
        template_fn = join(template_dir, template_fn)
        with open(template_fn, "r") as f:
            template_str = f.read()

        # fill in the template
        formatted = template_str.format(mutate_residue_placeholders="\n".join(mutate_residue_blocks),
                                        protocols_placeholders="\n".join(protocols),
                                        resnums_str_placeholder=resnum_str,
                                         **rosetta_hparams_str)

        with open(join(out_dir, output_fn), "w") as f:
            f.write(formatted)