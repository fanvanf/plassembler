import os
import sys
import subprocess as sp
from src.external_tools import ExternalTool
from loguru import logger
from pathlib import Path
import gzip
import shutil



def chopper(input_long_reads, outdir, min_length, min_quality, gzip_flag, threads, logdir):
    """Filters long reads using chopper

    :param input_long_reads: input ONT reads file
    :param outdir: output directory
    :param min_length: minimum length for long reads - defaults to 1000
    :param min_quality:  minimum quality for long reads - defaults to 8
    :param gzip_flag: whether or not the long reads are gzipped
    :param logdir
    :return:
    """
    filtered_long_reads : Path = Path(outdir)/f"chopper_long_reads.fastq.gz"
    logger.info(f"Started running chopper")
    logdir.mkdir(parents=True, exist_ok=True)
    tool = "chopper"
    tool_name = Path(tool).name
    logfile_prefix: Path = logdir / f"{tool_name}"
    err_log = open(f"{logfile_prefix}.err", "w")
    f = open(filtered_long_reads, "w")
    if gzip_flag == True:
        try:
            unzip = sp.Popen(["gunzip", "-c", input_long_reads], stdout=sp.PIPE)
            chopper = sp.Popen(
                [
                    "chopper",
                    "-q",
                    min_quality,
                    "--threads",
                    threads,
                    "-l",
                    min_length,
                    "--headcrop",
                    "25",
                    "--tailcrop",
                    "25",
                ],
                stdin=unzip.stdout,
                stdout=sp.PIPE, 
                stderr=err_log
            )
            gzip = sp.Popen(["gzip"], stdin=chopper.stdout, stdout=f)
            output = gzip.communicate()[0]
        except:
            logger.error("Error with chopper")
    else:
        try:
            cat = sp.Popen(["cat", input_long_reads], stdout=sp.PIPE)
            chopper = sp.Popen(
                [
                    "chopper",
                    "-q",
                    min_quality,
                    "--threads",
                    threads,
                    "-l",
                    min_length,
                    "--headcrop",
                    "25",
                    "--tailcrop",
                    "25",
                ],
                stdin=cat.stdout,
                stdout=sp.PIPE, 
                stderr=err_log
            )
            gzip = sp.Popen(["gzip"], stdin=chopper.stdout, stdout=f)
            output = gzip.communicate()[0]
        except:
            logger.error("Error with chopper")
    logger.info(f"Finished running chopper")



def fastp(short_one, short_two, outdir, logdir):
    """Trims short reads using fastp

    :param short_one:  R1 short read file
    :param short_two:  R2 short read file
    :param outdir: output directory
    :param logger: logger
    :return:
    """
    outdir = Path(outdir)
    out_one: Path  = outdir/f"trimmed_R1.fastq"
    out_two: Path  = outdir/f"trimmed_R2.fastq"

    fastp = ExternalTool(
        tool="fastp",
        input=f"--in1 {short_one} --in2 {short_two}",
        output=f"--out1 {out_one} --out2 {out_two}",
        params=f"",
        logdir=logdir,
        outfile=""
    )

    ExternalTool.run_tool(fastp, to_stdout=False)


def copy_sr_fastq_file(infile: Path, outfile: Path):
    if infile.suffix == ".gz":
        # If the input file is a .fastq.gz file, extract and copy to .fastq
        with gzip.open(infile, 'rt') as f_in:
            with open(outfile, 'w') as f_out:
                f_out.writelines(f_in)
    elif infile.suffix == ".fastq":
        # If the input file is already a .fastq file, copy it directly
        shutil.copy2(infile, outfile)
    else:
        # Skip files that are not .fastq or .fastq.gz
        logger.error("Error with copy_sr_fastq_file")