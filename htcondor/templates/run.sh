#!/usr/bin/env bash


# exit if any command fails...
set -e

CODE_FN=code.tar.gz


# create output directory for condor logs early
# not sure exactly when/if this needs to be done
mkdir -p output/condor_logs

# echo some HTCondor job information
echo "Date: $(date)"
echo "Host: $(hostname)"
echo "System: $(uname -spo)"
echo "_CONDOR_JOB_IWD: $_CONDOR_JOB_IWD"
echo "Cluster: $CLUSTER"
echo "Process: $PROCESS"
echo "RunningOn: $RUNNINGON"

# now that we are using aptainer we need to start initializing conda
. /opt/conda/etc/profile.d/conda.sh
conda activate metl-sim


# this makes it easier to set up the environments, since the PWD we are running in is not $HOME
export HOME=$PWD



# combine any split tar files into a single file (this will probably just be the rosetta distribution)
if [ "$(ls 2>/dev/null -Ubad1 -- *.tar.gz.* | wc -l)" -gt 0 ];
then
  # first get all the unique split tar file prefixes
  declare -A tar_prefixes
  for f in *.tar.gz.*; do
      tar_prefixes[${f%%.*}]=
  done
  # now combine the split tar files for each prefix
  for f in "${!tar_prefixes[@]}"; do
    echo "Combining split files for $f.tar.gz"
    cat "$f".tar.gz.* > "$f".tar.gz
    rm "$f".tar.gz.*
  done
fi

# the code tar file needs a special flag to un-tar properly
# remove the enclosing folder with strip-components
if [ -f "$CODE_FN" ]; then
  echo "Extracting $CODE_FN"
  tar -xf $CODE_FN --strip-components=1
  rm $CODE_FN
fi


# extract rosetta and any additional tar files that might contain additional data
if [ "$(ls 2>/dev/null -Ubad1 -- *.tar.gz | wc -l)" -gt 0 ];
then
  for f in *.tar.gz;
  do
    echo "Extracting $f"
    tar -xf "$f";
    rm "$f"
  done
fi


# launch our python run script with argument file number
echo "Launching ${PYSCRIPT}"
python3 code/${PYSCRIPT} @energize_args.txt --variants_fn="${PROCESS}.txt" --cluster="$CLUSTER" --process="$PROCESS" --commit_id="$GITHUB_TAG"