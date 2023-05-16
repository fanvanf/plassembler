#!/usr/bin/env python3
import os
import logging
import time
import datetime
import input_commands
import qc
import mapping
import assembly
import cleanup
import log
import run_mash
import install_database
import bam
from plass_class import Plass
from plass_class import Assembly
import sam_to_fastq
import concat
import test_incompatibility
import run_unicycler
import multimer



from version import __version__

v = __version__

if __name__ == "__main__":

    # get start time
    start_time = time.perf_counter()

    start_cpu_time = time.process_time()

    # getting time for log file 
    time_for_log = datetime.datetime.now().strftime("%m%d%Y_%H%M%S")

    # get inputs
    args = input_commands.get_input()

    # set the prefix
    if args.prefix == "Default":
        prefix = "plassembler"
    else:
        prefix = args.prefix

    # instiate the output directory
    out_dir = input_commands.instantiate_dirs(args.outdir, args.force) # incase there is already an out_dir

    # beginning logging
    LOG_FILE = os.path.join(out_dir, prefix + "_" + str(time_for_log) + ".log")
    logger = logging.getLogger()
    logging.basicConfig(level=logging.INFO,filename=LOG_FILE,format='%(asctime)s - %(levelname)s - %(message)s')
    message = "Starting plassembler v" + v
    log.write_message(message, logger)

    # add the inputs to the log
    logging.info("Input args: %r", args)

    # check deps 
    message = "Checking dependencies."
    log.write_message(message, logger)
    input_commands.check_dependencies(logger)

    # check the mash database is installed
    message = "Checking database installation."
    log.write_message(message, logger)
    database_installed = install_database.check_db_installation(args.database)
    if database_installed == True:
        message = "Database successfully checked."
        log.write_message(message, logger)
    else:
        message = "\nPlease run install_database.py \n"
        log.print_and_exit(message, logger)

#############################
######### assembled_mode == true 
#############################

    if args.assembled_mode == True:

        assembly = Assembly()
        assembly.out_dir = out_dir
        assembly.threads = args.threads

        message = "\n###########################"
        log.write_message(message, logger)
        message ="You have chosen to specify an input assembly FASTA file containing plasmids to calculate depth and PLSDB type. \nNo assembly will be conducted."
        log.write_message(message, logger)
        message = "###########################\nAssembled Mode Activated\n###########################\n"
        log.write_message(message, logger)

        # validation
        message = "Checking input FASTAs."
        log.write_message(message, logger)
        input_commands.validate_fastas_assembled_mode(args.input_chromosome, args.input_plasmids)

        message = "Checking input FASTQs."
        log.write_message(message, logger)
        (short_flag, long_flag, long_gzipped) = input_commands.validate_fastqs_assembled_mode(args.longreads, args.short_one, args.short_two)

        # assign the 
        assembly.short_flag = short_flag
        assembly.long_flag = long_flag

        if long_flag == True:
            message = "Filtering long reads."
            log.write_message(message, logger)
            qc.chopper(args.longreads, out_dir, args.min_length, args.min_quality, long_gzipped, args.threads)
            # doesn't subsample by default for assembled mode
            #qc.rasusa(out_dir, False, args.subsample_depth, args.chromosome, logger)
        if short_flag == True:
            message = "Trimming short reads."
            log.write_message(message, logger)
            qc.trim_short_read(args.short_one, args.short_two, out_dir,  logger)

        message = "Calculating Depths."
        log.write_message(message, logger)

        assembly.combine_input_fastas(args.input_chromosome, args.input_plasmids)
        assembly.get_depth(args.threads)

        # runs mash 
        message = 'Calculating mash distances to PLSDB.'
        log.write_message(message, logger)
        run_mash.mash_sketch(out_dir, args.input_plasmids, logger)
        run_mash.run_mash(out_dir, args.database, logger)

        # processes output
        assembly.process_mash_tsv(args.database, args.input_plasmids)
        # combine depth and mash tsvs
        assembly.combine_depth_mash_tsvs(prefix)

        # heuristic check forQC
        test_incompatibility.incompatbility(assembly.combined_depth_mash_df, logger)

        # rename contigs and update copy number with plsdb
        cleanup.move_and_copy_files(out_dir, prefix, False, args.keep_fastqs, True, args.long_only)
        cleanup.remove_intermediate_files(out_dir, args.keep_chromosome, True, args.long_only)


#############################
# not in assembled_mode -> main mode 
#############################

    else:
        message = 'Checking input fastqs.'
        log.write_message(message, logger)

        if args.longreads == 'nothing':
            message = 'ERROR:You have not input a long read FASTQ file with -l. Please check your input.'
            log.print_and_exit(message, logger)

        # experimental long only - high quality long read only
        if args.long_only == False:
            if args.short_one == 'nothing':
                message = "ERROR: You have not input a short read R1 FASTQ file with -1. Please check your input."
                log.print_and_exit(message, logger)
            if args.short_two == 'nothing':
                message = "ERROR: You have not input a short read R2 FASTQ file with -2. Please check your input."
                log.print_and_exit(message, logger)
        else:
            message = "You have chosen --long_only with long reads only. Ignoring any short reads."
            log.write_message(message, logger)
        
        # checking fastq 
        # if long reads
        long_zipped = input_commands.validate_fastq(args.longreads)

        if args.long_only == False:
            s1_zipped = input_commands.validate_fastq(args.short_one)
            s2_zipped = input_commands.validate_fastq(args.short_two)

        # filtering long readfastq
        message ="Filtering long reads with chopper."
        log.write_message(message, logger)
        min_quality = args.min_quality
        if args.long_only == True:
            if int(min_quality) < 15:
                message = "Increasing min quality to 15 in long only mode."
                log.write_message(message, logger)
                min_quality = str(15)
        qc.chopper(args.longreads, out_dir, args.min_length, min_quality, long_zipped, args.threads)
        # if args.subsample == True:
        #     message ="Subsampling long reads with rasusa."
        #     log.write_message(message, logger)

        #  qc.rasusa(out_dir, args.subsample, args.subsample_depth, args.chromosome, logger )

        # pacbio model check that the string is valid
        if args.pacbio_model != "nothing":
            pacbio_model = input_commands.validate_pacbio_model(args.pacbio_model, logger)
        else:
            pacbio_model = args.pacbio_model


        # running Flye
        message = "Running Raven."
        log.write_message(message, logger)

        # just keep Flye as placeholder experimental for now
        if args.long_only == True:
            assembly.run_flye(out_dir, args.threads, args.raw_flag, pacbio_model, logger)
        else:
            assembly.run_raven(out_dir, args.threads,  logger)

        # instanatiate the class with some of the commands
        plass = Plass()
        plass.out_dir = out_dir
        plass.threads = args.threads
        plass.long_only = args.long_only

        # count contigs and add to the object
        message = "Counting Contigs."
        log.write_message(message, logger)
        plass.get_contig_count(logger)

        ####################################################################
        # Case 1: where there is only 1 contig -> means that chromosome was assembled, no plasmids in the long read only assembly, and  attempt recovery with short reads
        ####################################################################

        if plass.contig_count == 1:

            # no_plasmids_flag = True as no plasmids
            plass.no_plasmids_flag = True

            # identifies chromosome and renames contigs
            # just keep Flye as placeholder experimental for now
            if args.long_only == True:
                message = "Only one contig was assembled with Flye."
                log.write_message(message, logger)
                plass.identify_chromosome_process_flye( args.chromosome, logger)
            else:
                message = "Only one contig was assembled with Raven."
                log.write_message(message, logger)
                plass.identify_chromosome_process_raven( args.chromosome, logger)

            # no chromosome identified - cleanup and exit
            ####################################################################
            if plass.chromosome_flag == False:
                message = 'No chromosome was identified. Likely, there was insufficient long read depth for Flye to assemble a chromosome. \nIncreasing sequencing depth is recommended. \nAlso please check your -c or --chromosome parameter, it may be too high. '
                log.write_message(message, logger)
                cleanup.move_and_copy_files(out_dir, prefix, False, args.keep_fastqs, False, args.long_only)
                cleanup.remove_intermediate_files(out_dir,args.keep_chromosome, False, args.long_only)
            else: # chromosome identified -> move on 
                if args.long_only == False:
                    message = 'Chromosome Identified. Plassembler will now use long and short reads to assemble plasmids accurately.'
                    log.write_message(message, logger)

                    message = 'Trimming short reads.'
                    log.write_message(message, logger)
                    qc.trim_short_read(args.short_one, args.short_two, out_dir,  logger)

                    message = 'Mapping long reads.'
                    log.write_message(message, logger)
                    mapping.minimap_long_reads(out_dir, args.threads, pacbio_model, logger)

                    #### short reads mapping
                    message = 'Mapping short reads.'
                    log.write_message(message, logger)
                    mapping.minimap_short_reads(out_dir, args.threads, logger)

                    message = 'Processing Sam/Bam Files and extracting Fastqs.'
                    log.write_message(message, logger)
                
                    # for long, custom function is quick enough
                    sam_to_fastq.extract_bin_long_fastqs(out_dir)

                    # for short, too slow so use samtools 
                    bam.sam_to_bam_short(out_dir, args.threads, logger)
                    bam.split_bams(out_dir, args.threads, logger)
                    bam.bam_to_fastq_short(out_dir, args.threads, logger)
                    concat.concatenate_short_fastqs(out_dir,logger)

                    # running unicycler
                    message = 'Running Unicycler.'
                    log.write_message(message, logger)

                    long_reads = os.path.join(out_dir, "plasmid_long.fastq")    
                    short_r1 = os.path.join(out_dir, "short_read_concat_R1.fastq")
                    short_r2 = os.path.join(out_dir, "short_read_concat_R2.fastq")

                    run_unicycler.run_unicycler(False, args.threads, logger, short_r1, short_r2, long_reads, 
                                                os.path.join(out_dir, "unicycler_output"))

                    # check for successful unicycler completion
                    plass.check_unicycler_success()

                    # if unicycler successfully finished, calculate the plasmid copy numbers
                    if plass.unicycler_success == True:

                        message ='Unicycler identified plasmids. Calculating Plasmid Copy Numbers.'
                        log.write_message(message, logger)

                        # get depth    
                        # as class so saves the depth dataframe nicely
                        plass.get_depth( logger, args.threads)

                        # run mash
                        message ='Calculating mash distances to PLSDB.'
                        log.write_message(message, logger)

                        # sketches the plasmids
                        run_mash.mash_sketch(out_dir, os.path.join(out_dir,"unicycler_output", "assembly.fasta"), logger)
                        # runs mash 
                        run_mash.run_mash(out_dir, args.database, logger)
                        # processes output
                        plass.process_mash_tsv( args.database)
                        # combine depth and mash tsvs
                        plass.combine_depth_mash_tsvs(prefix)

                        # rename contigs and update copy bumber with plsdb
                        plass.finalise_contigs(prefix)

                        # heuristic check only if not long_only
                        if args.long_only == False:
                        # heuristic check 
                            test_incompatibility.incompatbility(plass.combined_depth_mash_df, logger)
                            #plass.add_multimer_info(prefix)

                        # cleanup files 
                        cleanup.move_and_copy_files(out_dir, prefix, True, args.keep_fastqs, False, args.long_only)
                        cleanup.remove_intermediate_files(out_dir,args.keep_chromosome, False, args.long_only)
                    
                    ####################################################################
                    # Case 4: where there are truly no plasmids even after unicycler runs
                    ####################################################################
                    else: # unicycler did not successfully finish, just cleanup and touch the files empty for downstream (snakemake)
                        message = "No plasmids found."
                        log.write_message(message, logger)
                        cleanup.move_and_copy_files(out_dir, prefix, False, args.keep_fastqs, False, args.long_only)
                        cleanup.remove_intermediate_files(out_dir,args.keep_chromosome, False, args.long_only)
                    
          
####################################################################
        # where more than 1 contig was assembled
####################################################################
        else:

            # no_plasmids_flag = False as no plasmids
            plass.no_plasmids_flag = False

            # identifies chromosome and renames contigs
            # just keep Flye as placeholder experimental for now for long read only
            if args.long_only == True:
                message = "More than one contig was assembled with Flye."
                log.write_message(message, logger)
                message = "Extracting Chromosome."
                log.write_message(message, logger)
                plass.identify_chromosome_process_flye( args.chromosome, logger)
            else:
                message = "More than one contig was assembled with Raven."
                log.write_message(message, logger)
                message = "Extracting Chromosome."
                log.write_message(message, logger)
                plass.identify_chromosome_process_raven( args.chromosome, logger)

            
            ####################################################################
            # Case 2 - where no chromosome was identified (likely below required depth) - need more long reads or user got chromosome parameter wrong - exit plassembler
            ####################################################################
            if plass.chromosome_flag == False:
                message = 'No chromosome was idenfitied. please check your -c or --chromosome parameter, it may be too high. \nLikely, there was insufficient long read depth for Flye to assemble a chromosome. Increasing sequencing depth is recommended.'
                log.write_message(message, logger)
                cleanup.move_and_copy_files(out_dir, prefix, False, args.keep_fastqs, False, args.long_only)
                cleanup.remove_intermediate_files(out_dir, args.keep_chromosome, False, args.long_only)

            ####################################################################
            # Case 3 - where a chromosome and plasmids were identified in the Flye assembly -> get reads mappeed to plasmids, unmapped to chromosome and assemble
            ####################################################################
            else:
                if args.long_only == False:
                    message = 'Chromosome Identified. Plassembler will now use long and short reads to assemble plasmids accurately.'
                    log.write_message(message, logger)

                    message = 'Mapping Long Reads.'
                    log.write_message(message, logger)
                    mapping.minimap_long_reads( out_dir, args.threads, pacbio_model, logger)

                 #### short reads trimming and  mapping
                    message = 'Trimming short reads.'
                    log.write_message(message, logger)
                    qc.trim_short_read(args.short_one, args.short_two, out_dir,  logger)

                    message = 'Mapping short reads.'
                    log.write_message(message, logger)
                    mapping.minimap_short_reads(out_dir, args.threads, logger)

                    message = 'Processing Sam/Bam Files and extracting Fastqs.'
                    log.write_message(message, logger)
            
                    # for long, custom function
                    # for short, too slow so use samtools
                    sam_to_fastq.extract_bin_long_fastqs(out_dir)

                    # short
                    # for short, too slow so use samtools 
                    bam.sam_to_bam_short(out_dir, args.threads, logger)
                    bam.split_bams(out_dir, args.threads, logger)
                    bam.bam_to_fastq_short(out_dir, args.threads, logger)
                    concat.concatenate_short_fastqs(out_dir,logger)


                    # running unicycler
                    message = 'Running Unicycler.'
                    log.write_message(message, logger)

                    long_reads = os.path.join(out_dir, "plasmid_long.fastq")
                    short_r1 = os.path.join(out_dir, "short_read_concat_R1.fastq")
                    short_r2 = os.path.join(out_dir, "short_read_concat_R2.fastq")

                    run_unicycler.run_unicycler(False, args.threads, logger, short_r1, short_r2, long_reads, 
                                                 os.path.join(out_dir, "unicycler_output"))

        
####################################################################
##### get copy number depths
####################################################################

                message = 'Calculating Plasmid Copy Numbers.'
                log.write_message(message, logger)
                
                # as class so saves the depth dataframe nicely
                plass.get_depth( logger, args.threads)

                # run mash
                message = 'Calculating mash distances to PLSDB.'
                log.write_message(message, logger)

                # sketches the plasmids
                run_mash.mash_sketch(out_dir, os.path.join(out_dir,"unicycler_output", "assembly.fasta"), logger)

                # runs mash 
                run_mash.run_mash(out_dir, args.database, logger)

                # processes output
                plass.process_mash_tsv(args.database)

                # combine depth and mash tsvs 
                plass.combine_depth_mash_tsvs(prefix)

                # rename contigs and update copy bumber with plsdb
                plass.finalise_contigs(prefix)

                # heuristic check 
                if args.long_only == False:
                    # incompatibility
                    test_incompatibility.incompatbility(plass.combined_depth_mash_df, logger)

                    # multimer check
                    #multimer.minimap2_unicycler_vs_flye_plasmids(out_dir, prefix, logger)

                    # combine depth and mash tsvs with dimer information
                    #plass.add_multimer_info(prefix)

                cleanup.move_and_copy_files(out_dir, prefix, True, args.keep_fastqs, False, args.long_only)
                cleanup.remove_intermediate_files(out_dir,args.keep_chromosome, False, args.long_only)

    # Determine elapsed time
    elapsed_wallclock_time = time.perf_counter() - start_time
    elapsed_wallclock_time = round(elapsed_wallclock_time, 2)

    # Show elapsed time for the process
    message = "Plassembler has finished."
    log.write_message(message, logger)

    message = "Elapsed time: "+str(elapsed_wallclock_time)+" seconds."
    log.write_message(message, logger)






