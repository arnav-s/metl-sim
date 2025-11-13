""" this is the run script that executes on the server """

import argparse
import subprocess
import shutil
import os
import sys
from os.path import isdir, join, basename
import uuid
import socket
import csv
import re

import shortuuid
import numpy as np
from scipy.sparse import csr_matrix
import pandas as pd
import h5py

from utils import return_pdb_chains
from templates import fill_templates
import time


class RosettaError(Exception):
    # a simple custom error for when Rosetta gives a bad return code
    pass


def prep_working_dir(template_dir, working_dir, pdb_fn, chain, variant,
                     rosetta_hparams, overwrite_wd=True):


    """ prep the working directory by copying over files from the template directory, modifying as needed """
    # delete the current working directory if one exists
    if overwrite_wd:
        try:
            shutil.rmtree(working_dir)
        except FileNotFoundError:
            pass

    # create the directory
    try:
        os.mkdir(working_dir)
    except FileExistsError:
        print("Working directory '{}' already exists. "
              "Delete it before continuing or set overwrite_wd=True.".format(working_dir),
              flush=True)
        raise

    # copy over PDB file into rosetta working dir and rename it to structure.pdb
    shutil.copyfile(pdb_fn, join(working_dir, "structure.pdb"))

    # fill the template rosetta arguments (Rosetta scripts XML files and resfile) for this variant
    # note that if the variant is the wild-type (no mutations), then there is no need to fill these in (wont be used)

    fill_templates(template_dir, chain, variant,rosetta_hparams, working_dir,pdb_fn)


    # copy over files from the template dir that don't need to be changed
    files_to_copy = os.listdir(template_dir)

    assert "relax.xml" not in files_to_copy, "Cannot name a file in template directory relax.xml - protected name , use relax_temp.xml instead for the template relax xml script"
    assert "flags_relax" not in files_to_copy , "Cannot name a file in template directory flags_relax - protected name, us flags_relax_temp instead for the template relax flags "



    for fn in files_to_copy:
        shutil.copy(join(template_dir, fn), working_dir)


def run_relax_step(rosetta_scripts_bin_fn, database_path, working_dir):

    # templates have been filled in to account if a variant_has_mutations=True
    # the _wt edge case has already been set through these flags.
    relax_cmd = [rosetta_scripts_bin_fn,
                 '-database', database_path,
                 '@flags_relax']

    relax_out_fn = join(working_dir, "relax.out")
    with open(relax_out_fn, "w") as f:
        return_code = subprocess.call(relax_cmd, cwd=working_dir, stdout=f, stderr=f)
    if return_code != 0:
        raise RosettaError("Relax step did not execute successfully. Return code: {}".format(return_code))


def run_filter_step(rosetta_scripts_bin_fn, database_path, working_dir):
    filter_cmd = [rosetta_scripts_bin_fn, '-database', database_path, '@flags_filter']
    filter_out_fn = join(working_dir, "filter.out")

    with open(filter_out_fn, "w") as f:
        return_code = subprocess.call(filter_cmd, cwd=working_dir, stdout=f, stderr=f)
    if return_code != 0:
        raise RosettaError("Filter step did not execute successfully. Return code: {}".format(return_code))


def run_pairwise_step(score_pairwise_bin_fn, database_path, working_dir):
    pairwise_cmd = [score_pairwise_bin_fn, '-database', database_path, '@flags_score_pairwise']
    pairwise_out_fn = join(working_dir, "pairwise.out")
    with open(pairwise_out_fn, "w") as f:
        return_code = subprocess.call(pairwise_cmd, cwd=working_dir, stdout=f, stderr=f)
    if return_code != 0:
        raise RosettaError("Pairwise pose evaluation did not execute successfully. Return code: {}".format(return_code))


def get_rosetta_paths():
    '''
    Paths must be on rosetta docker container
    '''

    # These binaries are packaged in the Docker container
    relax_bin_fn = 'relax'
    rosetta_scripts_bin_fn = 'rosetta_scripts'
    score_jd2_bin_fn = "score_jd2"
    score_pairwise_bin_fn = "residue_energy_breakdown"
    database_path = '/usr/local/database'


    return relax_bin_fn, rosetta_scripts_bin_fn, score_jd2_bin_fn, score_pairwise_bin_fn, database_path

def quantize_float_data(float_data, quantized_dtype=np.int8):
    x_min = float_data.min()
    x_max = float_data.max()
    quantized_min = np.iinfo(quantized_dtype).min
    quantized_max = np.iinfo(quantized_dtype).max

    s = (x_max - x_min)/(quantized_max - quantized_min)
    z = quantized_min - (x_min/s)

    quantized_data = np.clip(np.round(float_data/s)+ z, quantized_min, quantized_max).astype(quantized_dtype)
    return quantized_data, s, z


def write_hdf_data(outFile, data_dict):
    for k,v in data_dict.items():
        group = outFile.create_group(k)
        quant_data, s, z = quantize_float_data(v.data)
        quant_grp = group.create_group("data")
        quant_grp.create_dataset("quantized_data", data=quant_data, dtype='i1')
        quant_grp.attrs['s'] = s
        quant_grp.attrs['z'] = z
        group.create_dataset("indices", data=v.indices)
        group.create_dataset("indptr", data=v.indptr)
        group.attrs["shape"] = v.shape

def write_pairwise_energies(database_file: str, pdb_fn: str, variant: str, pairwise_scores: dict):
    with h5py.File(database_file, "a") as outFile:
        if pdb_fn not in outFile:
            grp = outFile.create_group(pdb_fn)
        else:
            grp = outFile[pdb_fn]
        if variant not in grp:
            grp = grp.create_group(variant)
        else:
            grp = grp[variant]
        write_hdf_data(grp, pairwise_scores)
        

def run_filter_pairwise_pipeline(working_dir:str,idx:str,run_times:dict,rosetta_hparams:dict):
    # now I need to fill in the flag files for the proper idx of interest
    template_fns = ["flags_score_pairwise_temp", "flags_filter_temp"]
    output_fns = ["flags_score_pairwise", "flags_filter"]

    rosetta_hparams_str = {k: str(v) for k, v in rosetta_hparams.items()}


    for template_fn, output_fn in zip(template_fns, output_fns):
        # load the template
        template_fn = join(working_dir,template_fn)
        with open(template_fn, "r") as f:
            template_str = f.read()


        # fill in the template
        formatted = template_str.format(idx_placeholder = idx,**rosetta_hparams_str)

        with open(join(working_dir, output_fn), "w") as f:
            f.write(formatted)


    # get the paths to the rosetta binaries and database
    relax_bin_fn, rosetta_scripts_bin_fn,  score_jd2_bin_fn, score_pairwise_bin_fn, database_path = get_rosetta_paths()

    filt_start_time = time.time()
    run_filter_step(rosetta_scripts_bin_fn, database_path, working_dir)
    filt_run_time = time.time() - filt_start_time

    # # print("Filter step took {:.2f}".format(filt_run_time))
    #
    pairwise_start_time = time.time()
    run_pairwise_step(score_pairwise_bin_fn, database_path, working_dir)
    pairwise_run_time = time.time() - pairwise_start_time

    run_times['pairwise'] = pairwise_run_time
    run_times['filter'] =  filt_run_time


    return run_times
def run_relax_pipeline(working_dir: str):



    # get the paths to the rosetta binaries and database
    relax_bin_fn, rosetta_scripts_bin_fn,  score_jd2_bin_fn, score_pairwise_bin_fn, database_path = get_rosetta_paths()


    # relax also needs to know whether the variant has mutations because it needs to either run relax
    # around just the mutated residues or around the whole structure
    rx_start_time = time.time()
    run_relax_step(rosetta_scripts_bin_fn, database_path, working_dir)
    rx_run_time = time.time() - rx_start_time
    # print("Relax step took {:.2f}".format(rx_run_time))



    run_times = { "relax": rx_run_time}

    return run_times


def parse_score_sc(score_sc_fn: str,
                   agg_method: str = "avg",
                   sort_col: str = "total_score"):
    """ parse the score.sc file from the energize run, aggregating energies and appending info about variant
        this function has also been co-opted to parse the centroid and filter score files, which should only
        have 1 possible record, so no need to do any agg (and it shouldn't) """

    with open(score_sc_fn, 'r') as inFile:
        first_line = inFile.readline().strip()
    if first_line == 'SEQUENCE:':
        score_df = pd.read_csv(score_sc_fn, delim_whitespace=True, skiprows=1, header=0)
    else:
        score_df = pd.read_csv(score_sc_fn, delim_whitespace=True, header=0)

    # drop the "SCORE:" and "description" columns, these won't be needed for final output

    score_df = score_df.drop(["SCORE:", "description"], axis=1)

    # special case: only 1 structure was generated, no need to aggregate
    if len(score_df) == 1:
        parsed_df = score_df.iloc[[0]]
        idx ='0001'
    else:
        if agg_method == "min_energy_avg":
            # select the structure(s) with the minimum total_score and average the energies if multiple structures
            # we average just in case there are some structures with the same min total_score but different energies
            min_score_df = score_df[score_df[sort_col] == score_df[sort_col].min()]

            # lets just take the first of this min_score_df as our final index structure
            idx = f"{min_score_df.index[0]+1:04d}"

            parsed_df = min_score_df.mean(axis=0).to_frame().T
            # min
        elif agg_method == "min_energy_first":
            # select structures with min total_score and use the first one
            min_score_df = score_df[score_df[sort_col] == score_df[sort_col].min()]

            parsed_df = min_score_df.iloc[[0]]
            idx = f"{parsed_df.index[0]+1:04d}"


            # for min energy first, we do the index of the structure with the lowest energy
        elif agg_method == "avg":
            # take the average of all structures, not just the ones with the lowest score
            parsed_df = score_df.mean(axis=0).to_frame().T
            # for index let's just do the first for average
            idx = f"{parsed_df.index[0]+1:04d}"


        else:
            raise ValueError("invalid aggregation method: {}".format(agg_method))

    parsed_df = parsed_df.reset_index(drop=True)
    return parsed_df,idx


def parse_pairwise_score(score_sc_fn: str):

    tbl = pd.read_csv(score_sc_fn, delim_whitespace=True, comment='#')
    score_cols = [c for c in tbl.columns if re.match(r'^fa_|^hbond|^rama|^total$', c)]
    L = tbl[['resi1','resi2']].replace({'--':0}).astype(int).values.max()

    mat = {t:np.zeros((L,L), dtype=np.float16) for t in score_cols}
    for _,row in tbl.iterrows():
        i = int(row.resi1) - 1
        j = int(row.resi2) - 1 if row.resi2 != '--' else i  # self row
        for term in score_cols:
            mat[term][i,j] = row[term]
            mat[term][j,i] = row[term]
    
    return {k: csr_matrix(v) for k, v in mat.items()}

def run_single_variant(pdb_fn, chain, variant, rosetta_hparams,
                       staging_dir, output_dir, template_dir, save_wd=False):
    # grab the start time for this variant
    start_time = time.time()

    # template_dir = "templates/energize_pairwise_wd_template"
    # todo: use a variant-specific working directory in the output directory (safer)
    working_dir = "energize_pairwise_wd"

    # if the working directory exists from a previously failed variant, remove it before starting new variant
    #
    if isdir(working_dir):
        shutil.rmtree(working_dir)

    chains = [chain.id for chain in return_pdb_chains(pdb_fn)]
    # verify to make sure that this is a monomer
    if len(chains)>1 or chains[0]!='A':
        raise ValueError(f"The PDB provided contains multiple chains, this code only supports pdb with chain A, "
                         f"found chains: {','.join(chains)}")

    # # # set up the working directory (copies the pdb file, sets up the rosetta scripts, etc)
    prep_working_dir(template_dir, working_dir, pdb_fn, chain, variant,rosetta_hparams, overwrite_wd=True)
    #
    # # run the mutate and relax steps
    variant_has_mutations = False if variant == "_wt" else True
    #
    run_times = run_relax_pipeline(working_dir)

    # copy over or parse any files we want to keep from the working directory to the output directory
    # the stdout and stderr outputs from rosetta are in the working directory under mutate.out and relax.out
    # however, we don't need them, so we are going to leave them there and just parse the energies

    # parse the output files into a single-record csv, appending info about variant
    # place in a staging directory and combine with other variants that run during this job

    score_df,idx = parse_score_sc(join(working_dir, "relax.sc"),agg_method = "min_energy_avg",sort_col="total_score")



    run_times=run_filter_pairwise_pipeline(working_dir,idx,run_times,rosetta_hparams)
    score_df=score_df.reset_index(drop=True)


    filter_df,_ = parse_score_sc(join(working_dir, "filter.sc"))

    # the total_score from filter and centroid probably won't be used, but let's keep them in just in case
    # just need to resolve the name conflict with the total_score from score_df
    filter_df.rename(columns={"total_score": "filter_total_score"}, inplace=True)

    full_df = pd.concat((score_df, filter_df), axis=1)

    run_times['all'] = time.time()-start_time

    # append info about this variant
    full_df.insert(0, "pdb_fn", [basename(pdb_fn)])
    full_df.insert(1, "variant", [variant])
    full_df.insert(2, "start_time", [time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(start_time))])
    full_df.insert(3, "run_time", [int(run_times["all"])])
    full_df.insert(4, "relax_run_time", [int(run_times["relax"])])
    full_df.insert(5, "filter_run_time", [int(run_times["filter"])])
    full_df.insert(6, "pairwise_run_time", [int(run_times["pairwise"])])

    # note: it's not the best practice to have filenames with periods and commas
    #   could pass in the loop ID for this single variant and use that to save the file
    full_df.to_csv(join(staging_dir, "{}_{}_energies.csv".format(basename(pdb_fn), variant)), index=False)

    # Read and dump pairwise energies in working dir

    # right now this only looks at the pairwise energies of the first output structure.
    # we would have to change the code to allow for multiple structures.
    pairwise_energies = parse_pairwise_score(join(working_dir, "pairwise_scores.tbl"))

    write_pairwise_energies(join(output_dir, "pairwise_energies.h5"), basename(pdb_fn), variant, pairwise_energies)

    # if the flag is set, save all files in the working directory for this variant
    # these go directly to the output directory instead of the staging directory
    if save_wd:
        shutil.copytree(working_dir, join(output_dir, "wd_{}_{}".format(basename(pdb_fn), variant)))

    # clean up the working dir in preparation for next variant
    shutil.rmtree(working_dir)



    return run_times["all"]


def get_log_dir_name(args, job_uuid, start_time, ld_prefix="energize"):
    """ get a log dir name for this run, whether running locally or on HTCondor """
    format_args = [ld_prefix,
                   args.cluster,
                   args.process,
                   time.strftime("%Y-%m-%d_%H-%M-%S", time.gmtime(start_time)),
                   job_uuid]
    log_dir_str = "{}_{}_{}_{}_{}"
    log_dir = log_dir_str.format(*format_args)
    return log_dir


def combine_outputs(staging_dir):
    """ combine the outputs from individual variants into a single csv """
    # Note that these will probably NOT be in the same order as they were run (can add timestamp to record)
    output_fns = [join(staging_dir, x) for x in os.listdir(staging_dir) if not x.startswith('pairwise_energies_') ]

    # read individual dataframes into a list
    dfs = []
    for fn in output_fns:
        df = pd.read_csv(fn, header=0)
        dfs.append(df)

    # combine into a single dataframe
    combined_df = pd.concat(dfs, axis=0, ignore_index=True)
    return combined_df


def save_csv_from_dict(save_fn, d):
    with open(save_fn, "w") as f:
        w = csv.writer(f)
        for k, v in d.items():
            w.writerow([k, v])


def save_argparse_args(args_dict, out_fn):
    """ save argparse arguments out to a file """
    with open(out_fn, "w") as f:
        for k, v in args_dict.items():
            # if a flag is set to false, dont include it in the argument file
            if (not isinstance(v, bool)) or (isinstance(v, bool) and v):
                f.write("--{}\n".format(k))
                # if a flag is true, no need to specify the "true" value
                if not isinstance(v, bool):
                    f.write("{}\n".format(v))


def save_job_info(script_start, job_uuid, cluster, process, commit_id, log_dir):
    # create an info file for this job (cluster, process, server, github commit id, etc.)
    start_time_utc = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(script_start))
    job_info = {"uuid": job_uuid, "cluster": cluster, "process": process, "hostname": socket.gethostname(),
                "github_commit_id": commit_id, "script_start_time": start_time_utc}
    save_csv_from_dict(join(log_dir, "job.csv"), job_info)


def main(args):
    # rough script start time for logging
    # this will be logged in UTC time (GM time) in the log directory name and output files
    script_start = time.time()

    # generate a unique identifier for this run
    job_uuid = shortuuid.encode(uuid.uuid4())[:12]

    # create the log directory for this job
    log_dir = join(args.log_dir_base, get_log_dir_name(args, job_uuid, script_start))
    os.makedirs(log_dir)

    # save the argparse arguments back out to a file
    save_argparse_args(vars(args), join(log_dir, "args.txt"))

    # save job info
    save_job_info(script_start, job_uuid, args.cluster, args.process, args.commit_id, log_dir)


    # error checking because right now code only
    # supported for these template directories
    allowed_template_dirs=['templates/energize_pairwise_wd_v6']
    if args.template_dir in allowed_template_dirs:
        pass
    else:
        ValueError(f"--template_dir must be in allowed template_dirs: {allowed_template_dirs}")


    if "torsional" == args.relax_optimization_and_scoring_scheme:
        relax_weights='beta_nov16'
        relax_cartesian_optimization = "false"
    elif "cartesian"==args.relax_optimization_and_scoring_scheme:
        relax_weights='beta_nov16_cart'
        relax_cartesian_optimization= "true"
    else:
        raise ValueError("--relax_optimization_and_scoring_scheme must be one of these values ['torsional','cartesian']")


    # create a dictionary of just rosetta hyperparameters that can be passed around throughout functions and saved
    rosetta_hparams = {"minimize_default_max_cycles": args.minimize_default_max_cycles,
                       "relax_repeats": args.relax_repeats,
                       "relax_nstruct": args.relax_nstruct,
                       "relax_repack_distance":args.relax_repack_distance,
                       "relax_minimize_distance":args.relax_minimize_distance,
                       "relax_additional_flags":"\n".join([f"-{val}" for val in args.relax_additional_flags]),
                       'relax_cartesian_optimization':relax_cartesian_optimization,
                       'relax_weights':relax_weights
                       }
    save_csv_from_dict(join(log_dir, "hparams.csv"), rosetta_hparams)

    # load the variants that will be processed with this run
    # this file contains a line for each variant
    # and each line contains the pdb file and the comma-delimited substitutions (e.g. "2qmt_p.pdb A23P,R67L")
    with open(args.variants_fn, "r") as f:
        pdbs_variants = f.read().splitlines()

    # set up the staging dir....
    staging_dir = join(log_dir, "staging")
    os.makedirs(staging_dir, exist_ok=True)

    # Setup h5 file for writing pairwise scores
    h5_file_path = join(log_dir, f"pairwise_energies.h5")
    with open(h5_file_path, "a") as oFile:
        os.utime(h5_file_path, None)

    # loop through each variant, model it with rosetta, save results
    # individual variant outputs will be placed in the staging directory
    failed = []  # keep track of any variants that file after 3 attempts
    for i, pdb_variant in enumerate(pdbs_variants):
        pdb_basename, variant = pdb_variant.split()
        pdb_fn = join(args.pdb_dir, pdb_basename)

        # sometimes a single variant fails but others were/are successful
        # give variants 3 attempts at success, then move on to other variants
        # in worst case scenario, there is a system-level problem that will cause all variants to fail
        num_attempts_per_variant = 3
        for attempt in range(num_attempts_per_variant):
            try:
                print("Running Rosetta on variant {} {} ({}/{})".format(basename(pdb_fn), variant,
                                                                        i + 1, len(pdbs_variants)), flush=True)
                run_time = run_single_variant(pdb_fn, args.chain, variant, rosetta_hparams, staging_dir,
                                              log_dir,args.template_dir, args.save_wd)
                print("Processing variant {} {} took {:.2f}".format(basename(pdb_fn), variant, run_time), flush=True)

            except (RosettaError, FileNotFoundError) as e:
                print(e, flush=True)
                print("Encountered error running variant {} {}. "
                      "Attempts remaining: {}".format(pdb_basename, variant, num_attempts_per_variant - attempt - 1),
                      flush=True)

                # if we are supposed to save the working directory, save it now
                # the run_single_variant() function doesn't take care of this when there's an exception
                # todo: if we end up using variant-specific working dir, update here
                working_dir = "energize_pairwise_wd"
                if args.save_wd:
                    shutil.copytree(working_dir, join(log_dir, "wd_{}_{}_{}".format(basename(pdb_fn), variant, attempt)))

                # clean up the working dir in preparation for next variant
                shutil.rmtree(working_dir)
            else:
                # successful variant run, so break out of the attempt loop
                break
        else:
            # else clause of the for loop triggers if we burned through all attempts without success
            # add this variant to a failed_variants.txt file and continue with the other variants
            failed.append(pdb_variant)

    # save a txt file with failed variants (if there are failed variants)
    if len(failed) > 0:
        with open(join(log_dir, "failed.txt"), "w") as f:
            for fv in failed:
                f.write("{}\n".format(fv))

    # if any variants were successful, concat the outputs into a final energies.csv
    if len(failed) < len(pdbs_variants):
        # combine outputs in the staging directory into a single csv file
        cdf = combine_outputs(join(log_dir, "staging"))
        # add additional column for job uuid
        cdf.insert(2, "job_uuid", job_uuid)
        # save in the main log directory
        cdf.to_csv(join(log_dir, "energies.csv"), index=False)

        os.system(f"tar cvjf \
                  {join(log_dir, 'pairwise_energies.h5')}.tar.bz2 \
                  {join(log_dir, 'pairwise_energies.h5')}")

    # compress outputs, delete the output staging directory, etc
    shutil.rmtree(join(log_dir, "staging"))

    if (len(failed) / len(pdbs_variants)) > args.allowable_failure_fraction:
        # too many variants failed in this job. exit with failure code.
        # todo: this exit code will put the job on hold, but the log directory will still be present with
        #  energies.csv, causing there to be duplicates for the variants that succeeded in this run and the
        #  variants that get run in the new run. one option is to just not save energies.csv when too many variants
        #  fail. the job will get rescheduled anyway and the variants will run on a new machine.
        #  but if we're going to run again, might as well keep the duplicate variants anyway? they get filtered out
        #  later...
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        fromfile_prefix_chars="@")

    # main input files

    parser.add_argument("--variants_fn",
                        help="path to text file containing protein variants",
                        type=str)


    # todo: change to specifying the chain in the variants_fn file to support different chains in a single run



    parser.add_argument("--chain",
                        help="the chain to use from the pdb file",
                        type=str,
                        default="A")

    parser.add_argument("--pdb_dir",
                        help="directory containing the pdb files referenced in variants_fn",
                        type=str,
                        default="pdb_files/prepared_pdb_files")


    parser.add_argument("--allowable_failure_fraction",
                        help="fraction of variants that can fail but still consider this job successful",
                        type=float,
                        default=0.25)



    parser.add_argument("--relax_optimization_and_scoring_scheme",
                        help="This will define the use of torsional (beta_nov16) or cartesian "
                             "(beta_nov16_cart) weights, and the optimization scheme during FastRelax."
                             "Output pose scoring's will also be based on this parameter.",
                        type=str,
                        default="torsional",
                        choices=['torsional','cartesian'])


    # energize hyperparameters
    parser.add_argument("--minimize_default_max_cycles",
                        help="number of optimization cycles in the minimization step (default in Rosetta is 2000)",
                        type=int,
                        default=2000)
    parser.add_argument("--relax_repeats",
                        help="number of FastRelax repeats in the relax step (default in rosetta is 5)"
                             "[Every repeat has 5 mininimization/repack cycles]",
                        type=int,
                        default=5)

    parser.add_argument("--relax_nstruct",
                        help="number of structures (restarts) in the relax step",
                        type=int,
                        default=1)
    parser.add_argument("--relax_repack_distance",
                        help="distance threshold for repacking sidechains from the mutated residues."
                             "(default is 10,000 Å or to repack all sidechains)",
                        type=float,
                        default=10000.0)

    parser.add_argument("--relax_minimize_distance",
                        help="distance threshold for minimizing backbone/sidechains from the mutated residues."
                             "(default is 10,000 Å or to minimize all residues)",
                        type=float,
                        default=10000.0)

    parser.add_argument(
        "--relax_additional_flags",
        help="Additional flags [DO NOT INCLUDE -, e.g ex1 instead "
             "of -ex1 (can be multiple, separated by newlines if using @file, )",
        nargs="+",  # allows multiple values
        type=str,
        default=[]
    )


    # logging and output options
    parser.add_argument("--save_wd",
                        help="set this flag to save the full working directory for each variant",
                        action="store_true")

    parser.add_argument("--log_dir_base",
                        help="base output directory where log dirs for each run will be placed",
                        default="output/energize_outputs")

    parser.add_argument("--template_dir",
                        help="template directory containing the xml files and flags for this particular rosetta run",
                        type=str,
                        default='templates/energize_pairwise_wd_v6',
                        choices=['templates/energize_pairwise_wd_v6'])


    # HTCondor job information and program run information
    parser.add_argument("--cluster",
                        help="cluster (when running on HTCondor)",
                        type=str,
                        default="local")

    parser.add_argument("--process",
                        help="process (when running on HTCondor)",
                        type=str,
                        default="local")

    parser.add_argument("--commit_id",
                        help="the github commit id corresponding to this version of the code",
                        type=str,
                        default="no_commit_id")

    main(parser.parse_args())
