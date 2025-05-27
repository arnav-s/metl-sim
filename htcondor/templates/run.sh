#!/usr/bin/env bash

CODE_FN=code.tar.gz
ENV_FN=metl-sim.tar.gz
ROSETTA_ENC_FN=rosetta_min_enc.tar.gz
ROSETTA_DEC_FN=rosetta_min.tar.gz
PASS_FILE=pass.txt

# exit if any command fails...
set -e

# create output directory for condor logs early
# not sure exactly when/if this needs to be done
mkdir -p output/condor_logs

# echo some HTCondor job information
echo "=== HTCondor Job Information ==="
echo "Date: $(date)"
echo "Host: $(hostname)"
echo "System: $(uname -spo)"
echo "_CONDOR_JOB_IWD: $_CONDOR_JOB_IWD"
echo "Cluster: $CLUSTER"
echo "Process: $PROCESS"
echo "RunningOn: $RUNNINGON"
echo "User: $(whoami)"
echo "Working Directory: $(pwd)"
echo "============================="
echo ""

# List initial files
echo "=== Initial Files in Directory ==="
ls -la
echo "============================="
echo ""

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
else
  echo "ERROR: Code archive '$CODE_FN' not found!"
  exit 1
fi

# set up the python environment (from packaged version)
# https://chtc.cs.wisc.edu/conda-installation.shtml

# the environment files need to be un-tarred into the "env" directory
# un-tar the environment files
if [ -f "$ENV_FN" ]; then
  echo "Extracting $ENV_FN"
  echo "Environment archive size: $(du -h $ENV_FN | cut -f1)"
  mkdir env
  tar -xzf $ENV_FN -C env
  rm $ENV_FN
  echo "Environment extracted successfully"
else
  echo "ERROR: Python environment archive '$ENV_FN' not found!"
  exit 1
fi

echo "Activating Python environment"
export PATH
. env/bin/activate

# Verify Python environment
echo "=== Python Environment Check ==="
echo "Python location: $(which python3)"
echo "Python version: $(python3 --version)"
echo "OpenSSL location: $(which openssl)"
echo "============================="
echo ""

# Handle Rosetta extraction with both encrypted and unencrypted cases
if [ -f "$ROSETTA_ENC_FN" ]; then
  # Encrypted version exists - decrypt it
  echo "Found encrypted Rosetta: $ROSETTA_ENC_FN"

  # Check if password file exists
  if [ ! -f "$PASS_FILE" ]; then
    echo "ERROR: Encrypted Rosetta found but password file '$PASS_FILE' is missing!"
    exit 1
  fi

  echo "Decrypting Rosetta"
  openssl version # echo the version for my knowledge
  openssl enc -d -aes256 -pbkdf2 -in "$ROSETTA_ENC_FN" -out "$ROSETTA_DEC_FN" -pass "file:$PASS_FILE"

  # Verify decryption was successful
  if [ $? -eq 0 ]; then
    echo "Successfully decrypted Rosetta"
    rm "$ROSETTA_ENC_FN"
  else
    echo "ERROR: Failed to decrypt Rosetta"
    exit 1
  fi

elif [ -f "$ROSETTA_DEC_FN" ]; then
  # Unencrypted version already exists
  echo "Found unencrypted Rosetta: $ROSETTA_DEC_FN (skipping decryption)"
else
  # Neither version exists - this might be an error
  echo "WARNING: No Rosetta archive found (neither $ROSETTA_ENC_FN nor $ROSETTA_DEC_FN)"
  exit 1
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
