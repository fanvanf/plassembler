#!/usr/bin/env python3
import os
import shutil
import sys
import time
from pathlib import Path

import click
from loguru import logger

from plassembler.utils.assembly import run_flye, run_raven
from plassembler.utils.bam import bam_to_fastq_short, sam_to_bam, split_bams
from plassembler.utils.cleanup import move_and_copy_files, remove_intermediate_files
from plassembler.utils.concat import concatenate_short_fastqs
from plassembler.utils.db import check_db_installation
from plassembler.utils.input_commands import (
    check_dependencies,
    validate_fastas_assembled_mode,
    validate_fastq,
    validate_fastqs_assembled_mode,
    validate_pacbio_model,
)
from plassembler.utils.mapping import minimap_long_reads, minimap_short_reads

# import classes
from plassembler.utils.plass_class import Assembly, Plass
from plassembler.utils.qc import chopper, copy_sr_fastq_file, fastp
from plassembler.utils.run_mash import mash_sketch, run_mash
from plassembler.utils.run_unicycler import run_unicycler
from plassembler.utils.sam_to_fastq import extract_bin_long_fastqs
from plassembler.utils.test_incompatibility import incompatbility
from plassembler.utils.util import get_version, print_citation

log_fmt = (
    "[<green>{time:YYYY-MM-DD HH:mm:ss}</green>] <level>{level: <8}</level> | "
    "<level>{message}</level>"
)


def begin_plassembler(outdir, force):
    """
    begins plassembler
    returns start time
    """
    # get start time
    start_time = time.time()
    # error out on sys.exit
    logger.add(lambda _: sys.exit(1), level="ERROR")

    # instantiate the outdir
    # remove outdir on force
    if force is True:
        if os.path.isdir(outdir) is True:
            shutil.rmtree(outdir)
        else:
            logger.info(
                f"--force was specified even though the directory {outdir} does not already exist. Continuing "
            )
    else:
        if os.path.isdir(outdir) is True:
            logger.error(
                f"Directory {outdir} already exists and force was not specified. Please specify -f or --force to overwrite {outdir}"
            )
    # instantiate outdir
    if os.path.isdir(outdir) is False:
        os.mkdir(outdir)

    # initial logging stuff
    log_file = os.path.join(outdir, f"plassembler_{start_time}.log")
    # adds log file
    logger.add(log_file)
    # ensure sys exit if error
    logger.info(f"You are using Plassembler version {get_version()}")
    logger.info("Repository homepage is https://github.com/gbouras13/plassembler")
    logger.info("Written by George Bouras: george.bouras@adelaide.edu.au")

    return start_time, outdir


def end_plassembler(start_time):
    """
    finishes plassembler
    """

    # Determine elapsed time
    elapsed_time = time.time() - start_time
    elapsed_time = round(elapsed_time, 2)

    # Show elapsed time for the process
    logger.info("Plassembler has finished")
    logger.info("Elapsed time: " + str(elapsed_time) + " seconds")


def run_options(func):
    """Run command line args
    Define common command line args here, and include them with the @common_options decorator below.
    """
    options = [
        click.option(
            "-d",
            "--database",
            help="Directory of PLSDB database.",
            type=click.Path(),
            required=True,
        ),
        click.option(
            "-l",
            "--longreads",
            help="FASTQ file of long reads.",
            type=click.Path(),
            required=True,
        ),
        click.option(
            "-1",
            "--short_one",
            help="R1 short read FASTQ file.",
            type=click.Path(),
            required=True,
        ),
        click.option(
            "-2",
            "--short_two",
            help="R2 short read FASTQ file.",
            type=click.Path(),
            required=True,
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def assembly_options(func):
    """Command line args for assembly
    Define common command line args here, and include them with the @common_options decorator below.
    """
    options = [
        click.option(
            "-d",
            "--database",
            help="Directory of PLSDB database.",
            type=click.Path(),
            required=True,
        ),
        click.option(
            "-l",
            "--longreads",
            help="FASTQ file of long reads.",
            type=click.Path(),
            default="nothing",
            show_default=False,
        ),
        click.option(
            "-1",
            "--short_one",
            help="R1 short read FASTQ file.",
            type=click.Path(),
            default="nothing",
            show_default=False,
        ),
        click.option(
            "-2",
            "--short_two",
            help="R2 short read FASTQ file.",
            type=click.Path(),
            default="nothing",
            show_default=False,
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def common_options(func):
    """Common command line args
    Define common command line args for all except install
    """
    options = [
        click.option(
            "-c",
            "--chromosome",
            help="Approximate lower-bound chromosome length of bacteria (in base pairs).",
            type=int,
            default=1000000,
            show_default=True,
        ),
        click.option(
            "-o",
            "--outdir",
            help="Directory to write the output to.",
            type=click.Path(),
            default="plassembler.output/",
            show_default=True,
        ),
        click.option(
            "-m",
            "--min_length",
            help="minimum length for filtering long reads with chopper.",
            type=str,
            default="500",
            show_default=True,
        ),
        click.option(
            "-q",
            "--min_quality",
            help="minimum quality q-score for filtering long reads with chopper.",
            type=str,
            default="9",
            show_default=True,
        ),
        click.option(
            "-t",
            "--threads",
            help="Number of threads.",
            type=str,
            default="1",
            show_default=True,
        ),
        click.option(
            "-f", "--force", is_flag=True, help="Force overwrites the output directory."
        ),
        click.option(
            "-p",
            "--prefix",
            help="Prefix for output files. This is not required.",
            type=str,
            default="plassembler",
            show_default=True,
        ),
        click.option("--skip_qc", is_flag=True, help="Skips qc (chopper and fastp)."),
        click.option(
            "--pacbio_model",
            help="Pacbio model for Flye. \nMust be one of pacbio-raw, pacbio-corr or pacbio-hifi. \nUse pacbio-raw for PacBio regular CLR reads (<20 percent error), pacbio-corr for PacBio reads that were corrected with other methods (<3 percent error) or pacbio-hifi for PacBio HiFi reads (<1 percent error).",
            type=str,
            default="nothing",
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


# click


@click.group()
@click.help_option("--help", "-h")
@click.version_option(get_version(), "--version", "-V")
def main_cli():
    1 + 1


"""
main
"""


@main_cli.command()
@click.help_option("--help", "-h")
@click.version_option(get_version(), "--version", "-V")
@click.pass_context
@run_options
@common_options
@click.option(
    "-r",
    "--raw_flag",
    help="Use --nano-raw for Flye. \nDesigned for Guppy fast configuration reads. \nBy default, Flye will assume SUP or HAC reads and use --nano-hq.",
    is_flag=True,
)
@click.option(
    "--keep_fastqs",
    help="Whether you want to keep FASTQ files containing putative plasmid reads \nand long reads that map to multiple contigs (plasmid and chromosome).",
    is_flag=True,
)
@click.option(
    "--keep_chromosome",
    help="If you want to keep the chromosome assembly.",
    is_flag=True,
)
@click.option(
    "--use_raven",
    help="Uses Raven instead of Flye for long read assembly. \nMay be useful if you want to reduce runtime.",
    is_flag=True,
)
def run(
    ctx,
    database,
    longreads,
    short_one,
    short_two,
    chromosome,
    outdir,
    min_length,
    min_quality,
    threads,
    force,
    prefix,
    use_raven,
    pacbio_model,
    skip_qc,
    raw_flag,
    keep_fastqs,
    keep_chromosome,
    **kwargs,
):
    """Runs Plassembler"""

    # initiate plassembler
    start_time, outdir = begin_plassembler(outdir, force)

    logger.info(f"Database directory is {database}")
    logger.info(f"Longreads file is {longreads}")
    logger.info(f"R1 fasta file is {short_one}")
    logger.info(f"R2 fasta file is {short_two}")
    logger.info(f"Chromosome length threshold is {chromosome}")
    logger.info(f"Output directory is {outdir}")
    logger.info(f"Min long read length is {min_length}")
    logger.info(f"Min long read quality is {min_quality}")
    logger.info(f"Thread count is {threads}")
    logger.info(f"--force is {force}")
    logger.info(f"--skip_qc is {skip_qc}")
    logger.info(f"--raw_flag is {raw_flag}")
    logger.info(f"--pacbio_model is {pacbio_model}")
    logger.info(f"--keep_fastqs is {keep_fastqs}")
    logger.info(f"--keep_chromosome is {keep_chromosome}")
    logdir = Path(f"{outdir}/logs")

    # check deps
    logger.info("Checking dependencies")
    check_dependencies()

    # check the mash database is installed

    logger.info("Checking database installation.")
    check_db_installation(Path(database), install_flag=False)
    # will only continue if successful
    logger.info("Database successfully checked.")

    # check fastqs
    logger.info("Checking input fastqs.")

    # check fastqs

    long_zipped = validate_fastq(longreads)
    s1_zipped = validate_fastq(short_one)
    s2_zipped = validate_fastq(short_two)

    logger.info(f"FASTQ file {longreads} compression is {long_zipped}")
    logger.info(f"FASTQ file {short_one} compression is {s1_zipped}")
    logger.info(f"FASTQ file {short_two} compression is {s2_zipped}")

    # pacbio model check that the string is valid if legit
    if pacbio_model != "nothing":
        pacbio_model = validate_pacbio_model(pacbio_model)

    if skip_qc is False:
        # filtering long readfastq
        logger.info("Filtering long reads with chopper")
        chopper(  # due to the stdin side of this, just implement the class maually in py
            longreads, outdir, min_length, min_quality, long_zipped, threads, logdir
        )

    else:  # copy the input to the outdir
        shutil.copy2(
            longreads,
            Path(f"{outdir}/chopper_long_reads.fastq.gz"),
        )

    # Raven for long only or '--use_raven'
    if use_raven is True:
        logger.info(
            "You have specified --use_raven. Using Raven for long read assembly."
        )
        logger.info("Running Raven.")
        run_raven(outdir, threads, logdir)
    else:
        logger.info("Running Flye.")
        run_flye(outdir, threads, raw_flag, pacbio_model, logdir)

    # instanatiate the class with some of the commands
    plass = Plass()
    plass.outdir = outdir
    plass.threads = threads
    plass.long_only = False

    # count contigs and add to the object
    logger.info("Counting Contigs.")
    plass.get_contig_count()

    ####################################################################
    # Case 1: where there is only 1 contig -> means that chromosome was assembled, no plasmids in the long read only assembly, and  attempt recovery with short reads
    ####################################################################

    if plass.contig_count == 1:
        # no_plasmids_flag = True as no plasmids
        plass.no_plasmids_flag = True

        # identifies chromosome and renames contigs
        if use_raven is True:
            logger.info("Only one contig was assembled with Raven.")
            plass.identify_chromosome_process_raven(chromosome)
        else:
            logger.info("Only one contig was assembled with Flye.")
            plass.identify_chromosome_process_flye(chromosome)

        #################################################
        # no chromosome identified - cleanup and exit
        ####################################################################
        if plass.chromosome_flag is False:
            move_and_copy_files(
                outdir,
                prefix,
                False,  # unicycler success
                keep_fastqs,
                False,  # assembled mode
                False,  # long only
                use_raven,
            )
            remove_intermediate_files(
                outdir,
                keep_chromosome,
                False,  # assembled mode
                False,  # long only
                use_raven,
            )
            message = "No chromosome was identified. Likely, there was insufficient long read depth to assemble a chromosome. \nIncreasing sequencing depth is recommended. \nAlso please check your -c or --chromosome parameter, it may be too high. "
            logger.error(message)
        else:  # chromosome identified -> move on
            logger.info(
                "Chromosome Identified. Plassembler will now use long and short reads to assemble plasmids accurately."
            )

            if skip_qc is True:  # copy the input to the outdir
                logger.info("Skipping short read trimming as --skip_qc was specified")
                out_one: Path = Path(outdir) / "trimmed_R1.fastq"
                out_two: Path = Path(outdir) / "trimmed_R2.fastq"
                copy_sr_fastq_file(Path(short_one), out_one)
                copy_sr_fastq_file(Path(short_two), out_two)
            else:
                logger.info("Trimming short reads.")
                fastp(short_one, short_two, outdir, logdir)

            logger.info("Mapping long reads.")
            input_long_reads: Path = Path(outdir) / "chopper_long_reads.fastq.gz"
            fasta: Path = Path(outdir) / "flye_renamed.fasta"
            sam: Path = Path(outdir) / "long_read.sam"
            minimap_long_reads(
                input_long_reads, fasta, sam, threads, pacbio_model, logdir
            )

            # short reads mapping
            samfile: Path = Path(outdir) / "short_read.sam"
            r1: Path = Path(outdir) / "trimmed_R1.fastq"
            r2: Path = Path(outdir) / "trimmed_R2.fastq"
            logger.info("Mapping short reads.")
            minimap_short_reads(r1, r2, fasta, samfile, threads, logdir)

            # for long, custom function is quick enough
            logger.info("Processing Sam/Bam Files and extracting Fastqs.")
            extract_bin_long_fastqs(outdir)

            # for short, too slow so use samtools
            samfile: Path = Path(outdir) / "short_read.sam"
            bamfile: Path = Path(outdir) / "short_read.bam"
            sam_to_bam(samfile, bamfile, threads, logdir)
            split_bams(outdir, threads, logdir)
            bam_to_fastq_short(outdir, threads, logdir)
            concatenate_short_fastqs(outdir)

            # running unicycler
            logger.info("Running Unicycler.")
            long_reads: Path = Path(outdir) / "plasmid_long.fastq"
            short_r1: Path = Path(outdir) / "short_read_concat_R1.fastq"
            short_r2: Path = Path(outdir) / "short_read_concat_R2.fastq"
            unicycler_dir: Path = Path(outdir) / "unicycler_output"

            run_unicycler(
                threads, logdir, short_r1, short_r2, long_reads, unicycler_dir
            )

            # check for successful unicycler completion
            plass.check_unicycler_success(unicycler_dir)

            # if unicycler successfully finished, calculate the plasmid copy numbers
            if plass.unicycler_success is True:
                logger.info(
                    "Unicycler identified plasmids. Calculating Plasmid Copy Numbers."
                )
                # get depth
                # as class so saves the depth dataframe nicely
                plass.get_depth(logdir, pacbio_model, threads)

                # run mash
                logger.info("Calculating mash distances to PLSDB.")

                # mash sketches the plasmids
                mash_sketch(
                    outdir,
                    os.path.join(outdir, "unicycler_output", "assembly.fasta"),
                    logdir,
                )
                # runs mash
                run_mash(outdir, database, logdir)
                # processes output
                plass.process_mash_tsv(database)
                # combine depth and mash tsvs
                plass.combine_depth_mash_tsvs(prefix)

                # rename contigs and update copy bumber with plsdb
                plass.finalise_contigs(prefix)

                # heuristic check
                incompatbility(plass.combined_depth_mash_df)

                # cleanup files
                move_and_copy_files(
                    outdir,
                    prefix,
                    True,  # unicycler success
                    keep_fastqs,
                    False,  # assembled mode
                    False,  # long only
                    use_raven,
                )
                remove_intermediate_files(
                    outdir,
                    keep_chromosome,
                    False,  # assembled mode
                    False,  # long only
                    use_raven,
                )

                ####################################################################
                # Case 4: where there are truly no plasmids even after unicycler runs
                ####################################################################
            else:  # unicycler did not successfully finish, just cleanup and touch the files empty for downstream (snakemake)
                logger.info("No plasmids found.")
                move_and_copy_files(
                    outdir,
                    prefix,
                    False,  # unicycler success
                    keep_fastqs,
                    False,  # assembled mode
                    False,  # long only
                    use_raven,
                )
                remove_intermediate_files(
                    outdir,
                    keep_chromosome,
                    False,  # assembled mode
                    False,  # long only
                    use_raven,
                )

    ####################################################################
    # where more than 1 contig was assembled
    ####################################################################
    else:
        # no_plasmids_flag = False as no plasmids
        plass.no_plasmids_flag = False

        # identifies chromosome and renames contigs
        # just keep Flye as placeholder experimental for now for long read only
        if use_raven is True:
            logger.info("More than one contig was assembled with Raven.")
            logger.info("Extracting Chromosome.")
            plass.identify_chromosome_process_raven(chromosome)
        else:
            logger.info("More than one contig was assembled with Flye.")
            logger.info("Extracting Chromosome.")
            plass.identify_chromosome_process_flye(chromosome)

        ####################################################################
        # Case 2 - where no chromosome was identified (likely below required depth) - need more long reads or user got chromosome parameter wrong - exit plassembler
        ####################################################################
        if plass.chromosome_flag is False:
            move_and_copy_files(
                outdir,
                prefix,
                False,  # unicycler success
                keep_fastqs,
                False,  # assembled
                False,  # long only
                use_raven,
            )
            remove_intermediate_files(
                outdir,
                keep_chromosome,
                False,  # assembled mode
                False,  # long only
                use_raven,
            )

            end_plassembler(start_time)
            logger.error(
                "No chromosome was idenfitied. please check your -c or --chromosome parameter, it may be too high. \nLikely, there was insufficient long read depth to assemble a chromosome. Increasing sequencing depth is recommended."
            )

        ####################################################################
        # Case 3 - where a chromosome and plasmids were identified in the Flye assembly -> get reads mappeed to plasmids, unmapped to chromosome and assemble
        ####################################################################
        else:
            message = "Chromosome Identified. Plassembler will now use long and short reads to assemble plasmids accurately."
            logger.info(message)

            logger.info("Mapping long reads.")
            input_long_reads: Path = Path(outdir) / "chopper_long_reads.fastq.gz"
            fasta: Path = Path(outdir) / "flye_renamed.fasta"
            sam_file: Path = Path(outdir) / "long_read.sam"
            minimap_long_reads(
                input_long_reads, fasta, sam_file, threads, pacbio_model, logdir
            )

            if skip_qc is True:  # copy the input to the outdir
                logger.info(f"Skipping short read trimming as --skip_qc is {skip_qc}")
                out_one: Path = Path(outdir) / "trimmed_R1.fastq"
                out_two: Path = Path(outdir) / "trimmed_R2.fastq"
                copy_sr_fastq_file(Path(short_one), out_one)
                copy_sr_fastq_file(Path(short_two), out_two)
            else:
                logger.info("Trimming short reads.")
                fastp(short_one, short_two, outdir, logdir)

            # short reads mapping
            logger.info("Mapping short reads.")
            samfile: Path = Path(outdir) / "short_read.sam"
            r1: Path = Path(outdir) / "trimmed_R1.fastq"
            r2: Path = Path(outdir) / "trimmed_R2.fastq"
            minimap_short_reads(r1, r2, fasta, samfile, threads, logdir)

            # for long, custom function is quick enough
            logger.info("Processing Sam/Bam Files and extracting Fastqs.")
            extract_bin_long_fastqs(outdir)

            # for short, too slow so use samtools
            samfile: Path = Path(outdir) / "short_read.sam"
            bamfile: Path = Path(outdir) / "short_read.bam"
            sam_to_bam(samfile, bamfile, threads, logdir)
            split_bams(outdir, threads, logdir)
            bam_to_fastq_short(outdir, threads, logdir)
            concatenate_short_fastqs(outdir)

            # running unicycler
            logger.info("Running Unicycler.")
            long_reads: Path = Path(outdir) / "plasmid_long.fastq"
            short_r1: Path = Path(outdir) / "short_read_concat_R1.fastq"
            short_r2: Path = Path(outdir) / "short_read_concat_R2.fastq"
            unicycler_dir: Path = Path(outdir) / "unicycler_output"

            run_unicycler(
                threads, logdir, short_r1, short_r2, long_reads, unicycler_dir
            )

            # check for successful unicycler completion
            plass.check_unicycler_success(unicycler_dir)

            ####################################################################
            # get copy number depths
            ####################################################################

            logger.info(
                "Unicycler identified plasmids. Calculating Plasmid Copy Numbers."
            )
            # get depth
            # as class so saves the depth dataframe nicely
            plass.get_depth(logdir, pacbio_model, threads)

            # run mash
            logger.info("Calculating mash distances to PLSDB.")

            # mash sketches the plasmids
            mash_sketch(
                outdir,
                os.path.join(outdir, "unicycler_output", "assembly.fasta"),
                logdir,
            )
            # runs mash
            run_mash(outdir, database, logdir)
            # processes output
            plass.process_mash_tsv(database)
            # combine depth and mash tsvs
            plass.combine_depth_mash_tsvs(prefix)

            # rename contigs and update copy bumber with plsdb
            plass.finalise_contigs(prefix)

            # heuristic check
            incompatbility(plass.combined_depth_mash_df)

            # cleanup files
            move_and_copy_files(
                outdir,
                prefix,
                True,  # unicycler success
                keep_fastqs,
                False,  # assembled mode
                False,  # long only
                use_raven,
            )
            remove_intermediate_files(
                outdir,
                keep_chromosome,
                False,  # assembled mode
                False,  # long only
                use_raven,
            )

    # end plassembler
    end_plassembler(start_time)


"""
assembled mode
"""


@main_cli.command()
@click.help_option("--help", "-h")
@click.version_option(get_version(), "--version", "-V")
@click.pass_context
@assembly_options
@common_options
@click.option(
    "--input_chromosome",
    help="Input FASTA file consisting of already assembled chromosome with assembled mode. \nMust be 1 complete contig.",
    type=str,
    default="nothing",
    show_default=False,
)
@click.option(
    "--input_plasmids",
    help="Input FASTA file consisting of already assembled plasmids with assembled mode. \nRequires FASTQ file input (short only, long only or long + short).",
    type=str,
    default="nothing",
    show_default=False,
)
def assembled(
    ctx,
    database,
    longreads,
    short_one,
    short_two,
    chromosome,
    outdir,
    min_length,
    min_quality,
    threads,
    force,
    prefix,
    skip_qc,
    input_chromosome,
    input_plasmids,
    pacbio_model,
    **kwargs,
):
    """Runs assembled mode"""

    # start times
    start_time, outdir = begin_plassembler(outdir, force)

    logger.info(f"Database directory is {database}")
    logger.info(f"Longreads file is {longreads}")
    logger.info(f"R1 fasta file is {short_one}")
    logger.info(f"R2 fasta file is {short_two}")
    logger.info(f"Chromosome length threshold is {chromosome}")
    logger.info(f"Output directory is {outdir}")
    logger.info(f"Min long read length is {min_length}")
    logger.info(f"Min long read quality is {min_quality}")
    logger.info(f"Thread count is {threads}")
    logger.info(f"--skip_qc is {skip_qc}")
    logger.info(f"--pacbio_model is {pacbio_model}")
    logdir = Path(f"{outdir}/logs")

    # check deps
    logger.info("Checking dependencies")
    check_dependencies()

    # check the mash database is installed

    logger.info("Checking database installation.")
    check_db_installation(Path(database), install_flag=False)
    # will only continue if successful
    logger.info("Database successfully checked.")

    # pacbio model check that the string is valid if legit
    if pacbio_model != "nothing":
        pacbio_model = validate_pacbio_model(pacbio_model)

    # instanatiate the class with some of the commands
    assembly = Assembly()
    assembly.outdir = outdir
    assembly.threads = threads

    # check FASTAs
    logger.info("Checking input FASTAs.")
    validate_fastas_assembled_mode(input_chromosome, input_plasmids)

    # check fastqs
    logger.info("Checking input fastqs.")

    (short_flag, long_flag, long_zipped) = validate_fastqs_assembled_mode(
        longreads, short_one, short_two
    )

    # assign the flags to object
    assembly.short_flag = short_flag
    assembly.long_flag = long_flag

    # filtering long readfastq
    if long_flag is True:
        if skip_qc is False:
            logger.info("Filtering long reads with chopper")
            chopper(  # due to the stdin side of this, just implement the class maually in py
                longreads, outdir, min_length, min_quality, long_zipped, threads, logdir
            )

        else:  # copy the input to the outdir
            shutil.copy2(
                longreads,
                Path(f"{outdir}/chopper_long_reads.fastq.gz"),
            )

    if short_flag is True:
        if skip_qc is True:  # copy the input to the outdir
            logger.info("Skipping short read trimming as --skip_qc was specified")
            out_one: Path = Path(outdir) / "trimmed_R1.fastq"
            out_two: Path = Path(outdir) / "trimmed_R2.fastq"
            copy_sr_fastq_file(Path(short_one), out_one)
            copy_sr_fastq_file(Path(short_two), out_two)
        else:
            logger.info("Trimming short reads.")
            fastp(short_one, short_two, outdir, logdir)

    logger.info("Calculating Depths.")
    assembly.combine_input_fastas(Path(input_chromosome), Path(input_plasmids))
    assembly.get_depth(logdir, threads, pacbio_model)

    # run mash
    logger.info("Calculating mash distances to PLSDB.")

    # mash sketches the plasmids
    mash_sketch(
        outdir,
        Path(input_plasmids),
        logdir,
    )
    # runs mash
    run_mash(outdir, database, logdir)
    # processes output
    assembly.process_mash_tsv(database, input_plasmids)
    # combine depth and mash tsvs
    assembly.combine_depth_mash_tsvs(prefix)

    # rename contigs and update copy number with plsdb
    move_and_copy_files(
        outdir,
        prefix,
        False,  # unicycler_success_flag
        False,  # keep fastqs
        True,  # assembled mode
        False,  # long only
        False,  # use raven
    )
    remove_intermediate_files(
        outdir,
        False,  # keep chrom
        True,  # assembled
        False,  # long only
        False,  # use raven
    )

    # end plassembler
    end_plassembler(start_time)


"""
download
"""


@main_cli.command()
@click.help_option("--help", "-h")
@click.version_option(get_version(), "--version", "-V")
@click.pass_context
@click.option(
    "-d",
    "--database",
    help="Directory where database will be stored.",
    type=click.Path(),
    required=True,
)
@click.option(
    "-f", "--force", is_flag=True, help="Force overwrites the database directory."
)
def download(ctx, database, force, **kwargs):
    """Downloads Plassembler DB"""

    logger.add(lambda _: sys.exit(1), level="ERROR")
    database = Path(database)
    logger.info(f"Checking database installation at {database}")
    check_db_installation(database, install_flag=True)  # t


"""
long only
"""


def long_options(func):
    """Run command line args
    Define common command line args here, and include them with the @common_options decorator below.
    """
    options = [
        click.option(
            "-d",
            "--database",
            help="Directory of PLSDB database.",
            type=click.Path(),
            required=True,
        ),
        click.option(
            "-l",
            "--longreads",
            help="FASTQ file of long reads.",
            type=click.Path(),
            required=True,
        ),
        click.option(
            "-c",
            "--chromosome",
            help="Approximate lower-bound chromosome length of bacteria (in base pairs).",
            type=int,
            default=1000000,
            show_default=True,
        ),
        click.option(
            "-o",
            "--outdir",
            help="Directory to write the output to.",
            type=click.Path(),
            default="plassembler.output/",
            show_default=True,
        ),
        click.option(
            "-m",
            "--min_length",
            help="minimum length for filtering long reads with chopper.",
            type=str,
            default="500",
            show_default=True,
        ),
        click.option(
            "-q",
            "--min_quality",
            help="minimum quality q-score for filtering long reads with chopper.",
            type=str,
            default="15",
            show_default=True,
        ),
        click.option(
            "-t",
            "--threads",
            help="Number of threads.",
            type=str,
            default="1",
            show_default=True,
        ),
        click.option(
            "-f", "--force", is_flag=True, help="Force overwrites the output directory."
        ),
        click.option(
            "-p",
            "--prefix",
            help="Prefix for output files. This is not required.",
            type=str,
            default="plassembler",
            show_default=True,
        ),
        click.option("--skip_qc", is_flag=True, help="Skips qc (chopper and fastp)."),
        click.option(
            "--pacbio_model",
            help="Pacbio model for Flye. \nMust be one of pacbio-raw, pacbio-corr or pacbio-hifi. \nUse pacbio-raw for PacBio regular CLR reads (<20 percent error), pacbio-corr for PacBio reads that were corrected with other methods (<3 percent error) or pacbio-hifi for PacBio HiFi reads (<1 percent error).",
            type=str,
            default="nothing",
        ),
        click.option(
            "-r",
            "--raw_flag",
            help="Use --nano-raw for Flye. \nDesigned for Guppy fast configuration reads. \nBy default, Flye will assume SUP or HAC reads and use --nano-hq.",
            is_flag=True,
        ),
        click.option(
            "--keep_chromosome",
            help="If you want to keep the chromosome assembly.",
            is_flag=True,
        ),
        click.option(
            "--use_raven",
            help="Uses Raven instead of Flye for long read assembly. \nMay be useful if you want to reduce runtime.",
            is_flag=True,
        ),
    ]
    for option in reversed(options):
        func = option(func)
    return func


@main_cli.command()
@click.help_option("--help", "-h")
@click.version_option(get_version(), "--version", "-V")
@click.pass_context
@long_options
def long(
    ctx,
    database,
    longreads,
    chromosome,
    outdir,
    min_length,
    min_quality,
    threads,
    force,
    prefix,
    use_raven,
    pacbio_model,
    skip_qc,
    raw_flag,
    keep_chromosome,
    **kwargs,
):
    """
    Plassembler with long reads only - experimental and untested
    """

    # start times
    start_time, outdir = begin_plassembler(outdir, force)

    logger.info(f"Database directory is {database}")
    logger.info(f"Longreads file is {longreads}")
    logger.info(f"Chromosome length threshold is {chromosome}")
    logger.info(f"Output directory is {outdir}")
    logger.info(f"Min long read length is {min_length}")
    logger.info(f"Min long read quality is {min_quality}")
    logger.info(f"Thread count is {threads}")
    logger.info(f"--force is {force}")
    logger.info(f"--skip_qc is {skip_qc}")
    logger.info(f"--raw_flag is {raw_flag}")
    logger.info(f"--pacbio_model is {pacbio_model}")
    logger.info(f"--keep_chromosome is {keep_chromosome}")
    logdir = Path(f"{outdir}/logs")

    # check deps
    logger.info("Checking dependencies")
    check_dependencies()

    # check the mash database is installed
    logger.info("Checking database installation.")
    check_db_installation(Path(database), install_flag=False)
    # will only continue if successful
    logger.info("Database successfully checked.")

    # check fastqs
    logger.info("Checking input fastqs.")

    # check fastqs
    long_zipped = validate_fastq(longreads)

    # pacbio model check that the string is valid if legit
    if pacbio_model != "nothing":
        pacbio_model = validate_pacbio_model(pacbio_model)

    if skip_qc is False:
        # filtering long readfastq
        logger.info("Filtering long reads with chopper")
        chopper(  # due to the stdin side of this, just implement the class maually in py
            longreads, outdir, min_length, min_quality, long_zipped, threads, logdir
        )

    else:  # copy the input to the outdir
        shutil.copy2(
            longreads,
            Path(f"{outdir}/chopper_long_reads.fastq.gz"),
        )

    # Raven for long only or '--use_raven'
    if use_raven is True:
        logger.info(f"--use_raven is {use_raven}. Using Raven for long read assembly.")
        logger.info("Running Raven.")
        run_raven(outdir, threads, logdir)
    else:
        logger.info("Running Flye.")
        run_flye(outdir, threads, raw_flag, pacbio_model, logdir)

    # instanatiate the class with some of the commands
    plass = Plass()
    plass.outdir = outdir
    plass.threads = threads
    plass.long_only = True

    # count contigs and add to the object
    logger.info("Counting Contigs.")
    plass.get_contig_count()

    if use_raven is True:
        plass.identify_chromosome_process_raven(chromosome)
    else:
        plass.identify_chromosome_process_flye(chromosome)

    if plass.chromosome_flag is False:
        move_and_copy_files(
            outdir,
            prefix,
            False,  # unicycler success
            False,  # keep fastqs
            False,  # assembled mode
            True,  # long only
            use_raven,
        )
        remove_intermediate_files(
            outdir,
            keep_chromosome,
            False,  # assembled mode
            True,  # long only
            use_raven,
        )
        message = "No chromosome was identified. Likely, there was insufficient long read depth to assemble a chromosome. \nIncreasing sequencing depth is recommended. \nAlso please check your -c or --chromosome parameter, it may be too high. "
        logger.error(message)

    else:
        ####################################################################
        # Only 1 contig
        ####################################################################

        if plass.contig_count == 1:
            # chromosome identified but no plasmids - just finish
            # end plassembler
            move_and_copy_files(
                outdir,
                prefix,
                False,  # unicycler success
                False,  # keep fastqs
                True,  # assembled mode
                False,  # long only
                use_raven,
            )
            remove_intermediate_files(
                outdir,
                keep_chromosome,
                False,  # assembled mode
                True,  # long only
                use_raven,
            )
            logger.error("Chromosome identified but no plasmids.")

        ####################################################################
        # Multiple Contigs
        ####################################################################

        elif plass.contig_count > 1:
            # no_plasmids_flag = False as obviously "plasmids"
            plass.no_plasmids_flag = False

            logger.info("Mapping long reads.")
            input_long_reads: Path = Path(outdir) / "chopper_long_reads.fastq.gz"
            fasta: Path = Path(outdir) / "flye_renamed.fasta"
            samfile: Path = Path(outdir) / "long_read.sam"
            minimap_long_reads(
                input_long_reads, fasta, samfile, threads, pacbio_model, logdir
            )

            # for long, custom function is quick enough
            logger.info("Processing Sam/Bam Files and extracting Fastqs.")
            extract_bin_long_fastqs(outdir)
            plass.get_depth_long(logdir, pacbio_model, threads)

            # run mash
            logger.info("Calculating mash distances to PLSDB.")

            # mash sketches the plasmids
            mash_sketch(outdir, os.path.join(outdir, "plasmids_initial.fasta"), logdir)

            # runs mash
            run_mash(outdir, database, logdir)

            # processes output
            plass.process_mash_tsv(database)

            # combine depth and mash tsvs
            plass.combine_depth_mash_tsvs(prefix)

            # rename contigs and update copy bumber with plsdb
            plass.finalise_contigs_long(prefix)

            # cleanup files
            move_and_copy_files(
                outdir,
                prefix,
                False,  # unicycler success
                False,  # keep fastqs
                False,  # assembled mode
                True,  # long only
                use_raven,
            )

            remove_intermediate_files(
                outdir,
                keep_chromosome,
                False,  # assembled mode
                True,  # long only
                use_raven,
            )

    # end plassembler
    end_plassembler(start_time)


@click.command()
def citation(**kwargs):
    """Print the citation(s) for this tool"""
    print_citation()


main_cli.add_command(citation)


def main():
    main_cli()


if __name__ == "__main__":
    main()
