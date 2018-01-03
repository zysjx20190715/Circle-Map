#!/data/xsh723/anaconda/bin/python3.6
from __future__ import division


import subprocess as sb
import warnings
import os
import pysam as ps
import pybedtools as bt
from Bio import pairwise2
from Bio.Seq import Seq
from Bio.Alphabet import generic_dna
import time
import sys
import pandas as pd
from utils import *

class realignment:
    """Class for managing the realignment and eccDNA indetification of circle-map"""

    def __init__(self, input_bam,qname_bam,genome_fasta,directory,mapq_cutoff,insert_size_mapq,insert_size_sample_size
                 ,ncores):
        self.input_bam = input_bam
        self.qname_bam = qname_bam
        self.genome_fa = genome_fasta
        self.directory = directory
        self.mapq_cutoff = mapq_cutoff
        self.insert_size_mapq = insert_size_mapq
        self.insert_sample_size = insert_size_sample_size
        self.cores = ncores



    def realignment(self):
        """Function that will iterate trough the bam file containing reads indicating eccDNA structural variants and
        will output a bed file containing the soft-clipped reads, the discordant and the coverage within the interval"""

        begin = time.time()

        os.chdir(self.directory)

        eccdna_bam = ps.AlignmentFile("%s" % self.input_bam, "rb")


        circ_peaks,sorted_bam = bam_circ_sv_peaks(eccdna_bam,self.input_bam,self.cores)

        print("Computing insert size and standard deviation from %s F1R2 reads with a mapping quality of %s" %
              (self.insert_sample_size,self.insert_size_mapq))

        insert_metrics = insert_size_dist(self.insert_sample_size,self.insert_size_mapq,self.qname_bam)

        print("The computed insert size is %f with a standard deviation of %s" % (insert_metrics[0],insert_metrics[1]))



        #Find a mate interval for every interval
        iteration = 0




        for interval in circ_peaks:
            iteration +=1
            print(iteration)

            #this holds the intervals where the discordant and SA mates have mapped
            candidate_mates = []
            for read in sorted_bam.fetch(interval.chrom, interval.start, interval.end,multiple_iterators=True):

                if read.mapq >= self.mapq_cutoff:

                    # create mate interval based on the soft-clipped SA alignments
                    if is_soft_clipped(read) == True and read.has_tag('SA'):

                        read_chr = sorted_bam.get_reference_name(read.reference_id)
                        suplementary = read.get_tag('SA')


                        # [chr, left_most start, "strand,CIGAR,mapq, edit_distance]
                        supl_info = [x.strip() for x in suplementary.split(',')]




                        if read_chr == supl_info[0] and int(supl_info[4]) >= self.mapq_cutoff:

                            #split read with the same orientation
                            if (read.is_reverse == True and supl_info[2] == '-') or (read.is_reverse == False and supl_info[2] == '+'):


                                #SA is downstream, the interval is start, start+read length

                                #Future Inigo, this part of the code is over complicated. you can create a function of this
                                if read.reference_start > int(supl_info[1]):

                                    ref_alignment_length = genome_alignment_from_cigar(supl_info[3])


                                    #ref_alignment_length * 2 is done for extending the realignment region
                                    #"SA" means that the realignment prior has been generated by a supplementary alignment
                                    # L means that the SA is aligned to to a rightmost part.

                                    mate_interval = [interval.chrom,int(supl_info[1])-(ref_alignment_length*2),(int(supl_info[1]) + (ref_alignment_length*2)),"SA","L"]

                                    candidate_mates.append(mate_interval)


                                #SA is upstream, the interval is end - read length, end
                                elif read.reference_start < int(supl_info[1]):

                                    ref_alignment_length = genome_alignment_from_cigar(supl_info[3])


                                    # ref_alignment_length * 2 is done for extending the realignment region, "SA" means that the realignment prior has been generated
                                    #by a supplementary alignment. R means that the SA is aligned to to a rightmost part.

                                    mate_interval = [interval.chrom,(int(supl_info[1])-(ref_alignment_length*2)),int(supl_info[1])+(ref_alignment_length*2),"SA","R"]

                                    candidate_mates.append(mate_interval)




                    # check discordant reads (R2F1 orientation)
                    elif read.is_unmapped  == False and read.mate_is_unmapped == False:

                        #check R2F1 orientation,when the R2 read
                        if read.is_reverse == True and read.mate_is_reverse == False:

                            #R2F1 order
                            if read.reference_start < read.next_reference_start:

                                if read.reference_id == read.next_reference_id:

                                    #create mate interval
                                    read_length = read.infer_query_length()

                                    # DR means that the realignment prior has been generated by the discordants. R means
                                    # that the mate has been aligned to a rightmost part

                                    mate_interval = [interval.chrom, read.next_reference_start,(read.next_reference_start + read_length),"DR","R"]
                                    candidate_mates.append(mate_interval)


                        #R2F1 when iterating trough F1 read
                        elif read.is_reverse == False and read.mate_is_reverse == True:

                            if read.next_reference_start < read.reference_start:

                                if read.reference_id == read.next_reference_id:



                                    # create mate interval
                                    read_length = read.infer_query_length()

                                    #L means that the mate is aligned to a leftmost part

                                    mate_interval = [interval.chrom, read.next_reference_start,(read.next_reference_start + read_length), "DR","L"]
                                    candidate_mates.append(mate_interval)
                        else:
                            #soft clipped without and SA and hard clipped reads (secondary)


                            if is_soft_clipped(read) == True and read.has_tag('SA') == False:
                                # mate interval is whole chromosome

                                if 'SQ' in sorted_bam.header:

                                    for reference in sorted_bam.header['SQ']:

                                        if reference['SN'] == sorted_bam.get_reference_name(read.reference_id):

                                            #LR is added just not to crash the program

                                            mate_interval = [interval.chrom, 1,reference['LN'], "SC","LR"]

                                            candidate_mates.append(mate_interval)


                                else:

                                    warnings.warn(
                                        "WARNING: the bam file does not have a SQ tag. Circle-Map cannot check the reference length for realigning\n"
                                        "soft clipped reads without a SA tag, hence, skipping. Please, check if your bam file is truncated")

                            elif is_hard_clipped(read):

                                # all hard clipped reads have SA tag with bwa, but just as sanity

                                if read.has_tag('SA'):
                                    # Future me, This part of the code could be OOP using the soft-clipped extraction

                                    read_chr = sorted_bam.get_reference_name(read.reference_id)

                                    suplementary = read.get_tag('SA')

                                    #[chr, left_most start, "strand,CIGAR,mapq, edit_distance]
                                    supl_info = [x.strip() for x in suplementary.split(',')]

                                    if read_chr == supl_info[0] and int(supl_info[4]) >= self.mapq_cutoff:

                                        # SA alignment with the same orientation
                                        if (read.is_reverse == True and supl_info[2] == '-') or (read.is_reverse == False and supl_info[2] == '+'):

                                            # SA is downstream, the interval is start, start+read length

                                            # Future Inigo, this part of the code is over complicated. you can create a function of this
                                            if read.reference_start > int(supl_info[1]):

                                                ref_alignment_length = genome_alignment_from_cigar(supl_info[3])

                                                # ref_alignment_length * 2 is done for extending the realignment region
                                                # "SA" means that the realignment prior has been generated by a supplementary alignment
                                                #L means that the SA is in a downstream region

                                                mate_interval = [interval.chrom,int(supl_info[1]) - (ref_alignment_length * 2),(int(supl_info[1]) + (ref_alignment_length * 2)), "SA","L"]

                                                candidate_mates.append(mate_interval)


                                            # SA is upstream, the interval is end - read length, end
                                            elif read.reference_start < int(supl_info[1]):

                                                ref_alignment_length = genome_alignment_from_cigar(supl_info[3])

                                                # ref_alignment_length * 2 is done for extending the realignment region, "SA" means that the realignment prior has been generated
                                                # by a supplementary alignment
                                                # R means that the SA is in a upstream region

                                                mate_interval = [interval.chrom,
                                                                 (int(supl_info[1]) - (ref_alignment_length * 2)),
                                                                 int(supl_info[1]) + (ref_alignment_length * 2), "SA","R"]

                                                candidate_mates.append(mate_interval)

                    else:
                        a=0

                        #hard clips, soft clipped without SA Double check

                else:
                    #low mapping quality reads, do nothing
                    continue

            if len(candidate_mates) > 0:

                # sort by column 4
                sorted_candidate_mates = sorted(candidate_mates, key=lambda x: x[3])
                candidate_mates = bt.BedTool(sorted_candidate_mates)
                # group by column 4. and get the minimum start point and the maximum end point
                grouped = candidate_mates.groupby(g=4, c=[1, 2, 3, 5], o=['distinct', 'min', 'max','distinct'])

                # reformat to fit pybedtools requirements and get pandas object. Usefull for calculations
                grouped_pandas = pd.read_table(grouped.fn, names=['read_type', 'chrom', 'start', 'stop','orientation'])
                grouped = grouped_pandas[['chrom', 'start', 'stop', 'read_type','orientation']]
                grouped = bt.BedTool.from_dataframe(grouped)

                realignment_interval = get_realignment_interval(grouped,grouped_pandas,insert_metrics)


                #print(grouped)
                # continue coding here






















        end = time.time()

        eccdna_bam.close()

        print((end-begin)/60)
