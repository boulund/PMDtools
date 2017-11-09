#!/usr/bin/env python3
# vim: syntax=python expandtab
# PMDtools Python3 rewrite by Fredrik Boulund 2017

"""
Author: Pontus Skoglund
Contact: pontus.skoglund@gmail.com
Date: January 23, 2014
Citation: P Skoglund, BH Northoff, MV Shunkov, AP Derevianko, S Paabo, 
          J Krause, M Jakobsson (2014) 
          Separating endogenous ancient DNA from modern day contamination in a Siberian Neandertal, 
          PNAS, advance online 27 January

Usage: python pmdtools.py <SAM formatted data with MD field present from stdin> [options]

Example:
   #remove all sequence reads with PMD score < 3
   samtools view -q 30 mybamfile.bam | python pmdtools.py --header --threshold 3 > samtools view -Sb - > mybamfile_filtered.bam
   
   #for more options:
   python pmdtools.py --help
   
   (for specification on the SAM format and a the samtools suite, see Li, Handsaker et al. 2009, Bioinformatics)
"""

__version__ = "PMDtools v0.50"

from sys import argv, exit, stdin, stderr
import argparse
import math
import re


def parse_args():
    parser = argparse.ArgumentParser(epilog=__version__)
    parser.add_argument("-n", "--number", dest="maxreads",
            default=(10**20),
            type=int,
            help="Stop after these many reads have been processed [%(default)s].")
    parser.add_argument("-c", "--chromosome", dest="chromosome",
            default="",
            type=str,
            help="Only process data from this chromosome [%(default)s].")
    parser.add_argument("-m", "--requiremapq", dest="mapq", metavar="MQ",
            default=0,
            type=int, 
            help="Only process sequences with mapping quality > MQ [%(default)s].")
    parser.add_argument("-q", "--requirebaseq", dest="baseq", metavar="BQ",
            default=0,
            type=int, 
            help="Only process bases with base quality > BQ [%(default)s].")
    parser.add_argument("-d", "--deamination", dest="deamination",  action="store_true",
            default=False,
            help="Output base frequencies in the read at positions where there are C or G in the reference [%(default)s].")
    parser.add_argument("--CpG", dest="cpg", action="store_true",
            default=False,
            help="Only use Cs and Gs in CpG context [%(default)s].")
    parser.add_argument("--range", dest="range", 
            default=30,
            type=int, 
            help="Output deamination patterns for this many positions from the sequence terminus [%(default)s].")
    parser.add_argument("--polymorphism_ancient", dest="polymorphism_ancient",
            default=0.001,
            type=float, 
            help="True biological polymorphism between the ancient individual and the reference sequence [%(default)s].")
    parser.add_argument("--polymorphism_contamination", dest="polymorphism_contamination",
            default=0.001,
            type=float, 
            help="True biological polymorphism between the contaminants and the reference sequence [%(default)s].")
    parser.add_argument("--PMDpparam", dest="PMDpparam",
            default=0.3,
            type=float, 
            help="Parameter p in geometric probability distribution of PMD [%(default)s].")
    parser.add_argument("--PMDconstant", dest="PMDconstant",
            default=0.01,
            type=float, 
            help="Constant C in geometric probability distribution of PMD [%(default)s].")
    parser.add_argument("-l", "--maxlength", dest="maxlength",
            default=200,
            type=int, 
            help="max length of a sequence")
    parser.add_argument("--noclips", dest="noclips", action="store_true",
            default=False,
            help="No clips [%(default)s].")
    parser.add_argument("--noindels", dest="noindels", action="store_true",
            default=False,
            help="No indels [%(default)s].")
    parser.add_argument("--onlyclips", dest="onlyclips", action="store_true",
            default=False,
            help="Only clips [%(default)s].")
    parser.add_argument("--onlydeletions", dest="onlydeletions", action="store_true",
            default=False,
            help="Only deletions [%(default)s].")
    parser.add_argument("--onlyinsertions", dest="onlyinsertions", action="store_true",
            default=False,
            help="Only insertions [%(default)s].")
    parser.add_argument("--nodeletions", dest="nodeletions", action="store_true",
            default=False,
            help="No deletions [%(default)s].")
    parser.add_argument("--noinsertions", dest="noinsertions", action="store_true",
            default=False,
            help="No insertions [%(default)s].")
    parser.add_argument("--notreverse", dest="notreverse", action="store_true",
            default=False,
            help="No reverse complement alignments [%(default)s].")
    parser.add_argument("-p", "--printDS", dest="printDS", action="store_true",
            default=False,
            help="Print PMD scores [%(default)s].")
    parser.add_argument("--printalignments", dest="printalignments", action="store_true",
            default=False,
            help="Print human readable alignments [%(default)s].")
    parser.add_argument("-t", "--threshold", dest="threshold", metavar="LT",
            default=-20000.0,
            type=float, 
            help="Only output sequences with PMD score > LT [%(default)s].")
    parser.add_argument("--upperthreshold", dest="upperthreshold", metavar="UT",
            default=1000000.0,
            type=float, 
            help="Only output sequences with PMD score < UT [%(default)s].")
    parser.add_argument("--perc_identity", dest="perc_identity",
            default=0.0,
            type=float, 
            help="Only output sequences with percent identity > T [%(default)s].")
    parser.add_argument("-a", "--adjustbaseq", dest="adjustbaseq", action="store_true",
            default=False,
            help="Apply PMD-aware adjustment of base quality scores specific to C>T and G>A mismatches to the reference [%(default)s].")
    parser.add_argument("--adjustbaseq_all", dest="adjustbaseq_all", action="store_true",
            default=False,
            help="Apply PMD-aware adjustment of base quality scores regardless of observed bases [%(default)s].")
    parser.add_argument("--dry", dest="dry", action="store_true",
            default=False,
            help="Print SAM input without any filters [%(default)s].")
    parser.add_argument("--header", dest="header", action="store_true",
            default=False,
            help="Output the SAM header [%(default)s].")
    parser.add_argument("--writesamfield", dest="writesamfield", action="store_true",
            default=False,
            help="Add 'DS:Z:<PMDS>' field to SAM output, will overwrite if already present [%(default)s].")
    parser.add_argument("-b", "--basic", dest="basic",
            default=0,
            type=int, 
            help="Only output reads with a C>T mismatch this many basepairs from the 5' end [%(default)s].")
    parser.add_argument("--stats", dest="stats", action="store_true",
            default=False,
            help="Output summarizing statistics to stderr [%(default)s].")

    if len(argv) < 2:
        parser.print_help()
        exit(1)
    
    return parser.parse_args()


def revcomp(inseq):
    inseq= inseq[::-1]
    newseq=''
    for inbase in inseq:
        if inbase == 'A': newseq += 'T'
        elif inbase == 'T': newseq += 'A'
        elif inbase == 'G': newseq += 'C'
        elif inbase == 'C': newseq += 'G'
        elif inbase == 'N': newseq += 'N'    
        elif inbase == '-': newseq += '-'
    return newseq


def phred2prob(Q):
    return 10.0 ** (-Q/10.0)


def prob2phred(P):
    return -10.0*math.log(P,10)


def L_match(fposition, fmodel, fquals, fpoly):
    P_damage = float(fmodel[fposition]) 
    P_error = phred2prob((ord(fquals[fposition])-33))/3.0
    P_poly = fpoly
    P_match = (1.0-P_damage)*(1.0-P_error)*(1.0-P_poly) + (P_damage*P_error*(1.0-P_poly)) + (P_error*P_poly * (1.0-P_damage))
    return P_match


def L_mismatch(fposition, fmodel, fquals, fpoly):
    P_damage = float(fmodel[fposition]) 
    P_error = phred2prob((ord(fquals[fposition])-33))/3.0
    P_poly = fpoly
    P_match = (1.0-P_damage)*(1.0-P_error)*(1.0-P_poly) + (P_damage*P_error*(1.0-P_poly)) + (P_error*P_poly * (1.0-P_damage))
    P_mismatch = 1.0-P_match
    return P_mismatch


def Newbaseq(fposition, fmodel, fquals):
    P_damage = float(fmodel[fposition]) 
    P_error = phred2prob( (ord(fquals[fposition])-33))/3.0
    NewErrorP = 1.0 - ((1.0-P_damage) * (1.0-P_error))
    return NewErrorP


def geometric(pval,kval,constant):
    return ((1.0-pval)**(kval-1))*pval + constant


def main():
    maxlen=options.maxlength
     
    modern_model_deam='0.001'
    modern_model_deam=modern_model_deam.split('\n')*1000 
    modern_model_deam=[float(l) for l in modern_model_deam]

    ancient_model_deam=[geometric(options.PMDpparam,l,options.PMDconstant) for l in range(1,1000)]

    if options.adjustbaseq_all:
        adjustment_model_deam=[geometric(options.PMDpparam,l,0.0) for l in range(1,1000)] ###constant is 0.0 here in contrast to the model used to compute PMD scores

    start_dict= {}

    ###base composition
    start_count = 0
    rev_start_count = 0
    not_counted = 0
    imperfect = 0

    mismatch_dict={}


    cigarparser = re.compile("([0-9]*)([A-Z])")


    start_dict_rev= {}
    mismatch_dict_rev={}


    deaminationlist=[]
    zpositionlist=[]
    ipositionlist=[]

    clipexcluded=0
    indelexcluded=0
    noMD=0
    noGCexcluded=0
    excluded_threshold=0
    passed=0
    noquals=0
    maskings=0


    line_counter = 0
    for line in sys.stdin: 
        if '@' in line[0]: 
            if options.header:
                print(line.rstrip('\n'))
            continue
        line_counter +=1

        col = line.split('\t')
        readname = col[0]
        position = int(col[3])
        chromosome = col[2]

        if options.chromosome:
            if chromosome != options.chromosome:continue
        MAPQ = int(col[4])
        read = col[9]
        readlen = len(read)
        quals= col[10]
        flag = col[1]
        position = int(col[3])
        cigar=col[5]

        if len(quals) <2:
            noquals+=1
            continue

        if options.noinsertions:
            if 'I' in cigar:continue 
        if options.nodeletions:
            if 'D' in cigar:continue 
        if options.onlyinsertions:
            if 'I' not in cigar:continue 
        if options.onlydeletions:
            if 'D' not in cigar:continue 
        if options.noindels:
            if 'I' in cigar or 'D' in cigar:
                indelexcluded +=1
                continue
        if options.noclips:
            if 'S' in cigar or 'H' in cigar or 'N' in cigar or 'P' in cigar:
                clipexcluded +=1
                continue
        if options.onlyclips:
            if 'S' not in cigar:
                continue
        if 'H' in cigar or 'P' in cigar or 'N' in cigar:
            prin('cigar found:', cigar, 'PMDtools only supports cigar operations M, I, S and D. The alignment has been excluded', file=stderr)
            continue
        if MAPQ < options.mapq: 
            continue
        if options.chromosome:
            if chromosome != options.chromosome: continue



        if flag.isdigit():
            if int(flag) & 16:
                reverse = True
            else:
                reverse = False
        else:
            if 'r' in flag: reverse = True
            elif 'r' not in flag: reverse = False

        if options.notreverse:
            if reverse: continue

        DSfield=False
        if 'DS:Z:' in line:
            DSfield=True
            PMDS= float(line.split('DS:Z:')[1].rstrip('\n').split()[0])
            LR=PMDS
            #print(PMDS)
        



        ##############
        # Recreate reference sequence from MD field
        ##############
        if (DSfield == False) or (options.writesamfield) or (options.basic > 0) or (options.perc_identity > 0.01) or (options.printalignments) or (options.adjustbaseq) or (options.adjustbaseq_all) or options.deamination or options.dry:
            
            read=col[9]
            ref_seq=''
            newread=''
        
            try:
                MD=line.split('MD:Z:')[1].split()[0].rstrip('\n')
            except IndexError:
                noMD+=1
                continue

            MDlist=re.findall('(\d+|\D+)',MD)

                
            MDcounter=0
            alignment=''
            for e in MDlist:
                if e.isdigit():
                    e=int(e)
                    alignment += '.'*e
                    ref_seq+= read[MDcounter:MDcounter+e]
                    newread+= read[MDcounter:MDcounter+e]
                    MDcounter+= int(e)

                elif '^' in e:
                    ef=e.lstrip('^')
                    alignment += ef
                    continue
                elif e.isalpha():
                    alignment += e
                    ref_seq+= e
                    newread+= read[MDcounter]
                    MDcounter+=len(e)

            if 'I' in cigar or 'S' in cigar:

                # find insertions and clips in cigar
                insertions=[]
                deletions=[]
                softclips=[]
                hardclips=[]
                paddings=[]
                cigarcount=0
                cigarcomponents=cigarparser.findall(cigar)
                for p in cigarcomponents:
                    cigaraddition=int(p[0])
                    if 'I' in p[1]: 
                        for c in range(cigarcount,cigarcount+cigaraddition): insertions.append(c)
                    elif  'S' in p[1]:
                        for c in range(cigarcount,cigarcount+cigaraddition): softclips.append(c)
                    cigarcount += int(p[0])
                # end cigar parsing

                # redo the read and ref using indel and clip info
                ref_seq=''
                newread =''
                alignmentcounter=0
                for x,r in zip(xrange(0,len(col[9])),read):
                    if x in insertions:
                        ref_seq += '-'
                        newread += read[x]
                    elif x in softclips:
                        ref_seq += '-'
                        newread += read[x]
                    else:
                        newread += read[x]
                        refbasealn=alignment[alignmentcounter]
                        if refbasealn == '.':
                            ref_seq += read[x]
                        else:
                            ref_seq += refbasealn
                        alignmentcounter +=1
                        
            if reverse:
                read = revcomp(read)
                ref_seq = revcomp(ref_seq)
                quals = quals[::-1]
            real_read=read
            real_ref_seq=ref_seq


        ##############
        # basic filter
        # prints the SAM line if a C>T mismatch with sufficient base quality is observed in the first n bases, where n is specified
        ##############
        if options.basic > 0:
            start_position = len(real_read) - len(real_read.lstrip('-'))
            for a,b,x in zip(real_read,real_ref_seq,range(0,len(real_ref_seq))):

                if a == 'N': continue
                if b == 'N': continue
                i = x - start_position
                if i >= readlen: break ###20
                if i > options.basic: break
                #print(a,b,i)
                if b == 'C' and a=='T' and ((ord(quals[i])-33) > options.baseq): 
                    print(line.rstrip('\n'))
                    break

            continue


        if options.perc_identity > 0.01 or options.printalignments:
            ##############
            # divergence filter
            ##############
            match=0
            mismatch=0
            mismatch_string=''
            for a,b in zip(real_read,real_ref_seq):
                thesebases=[a,b]
                if '-' in thesebases: 
                    mismatch_string+='-'
                    continue
                if a == 'N': continue
                if b == 'N': continue
                if a == b: 
                    mismatch_string+='|'
                    match +=1
                elif a!=b: 
                    mismatch_string+='x'
                    if 'C' == b and 'T' == a: continue
                    if 'G' == b and 'A' == a: continue
                    mismatch +=1    
            
            try:
                perc_identity=1.0*match/(match+mismatch)
            except ZeroDivisionError:
                continue
            if perc_identity < options.perc_identity:continue





        ##############
        #start PMD score computations
        ##############

        if (DSfield == False) or (DSfield == True and options.writesamfield == True) or (options.basic > 0) or options.adjustbaseq or options.adjustbaseq_all or options.deamination or options.dry:
            L_D=1.0
            L_M=1.0

            newquals=quals
            start_position = 0
            back_start_position = len(real_read)-1
            for a,b,x in zip(real_read,real_ref_seq,range(0,len(real_ref_seq))):
                if 'N' in [a,b]: continue
                i = x - start_position
                z = back_start_position - x 
                qualsrev=quals[::-1]
                if i >= readlen: break ###20

                if options.adjustbaseq_all:
                    newprob= adjustment_model_deam[i]+adjustment_model_deam[z] + phred2prob(ord(quals[i])-33)
                    #newprob=min(newprob,1.0)
                    newphred=int(prob2phred(newprob))
                    newqual=chr(int(newphred)+33)                        
                    newquals=quals[0:i]+newqual+quals[(i+1):]

                if (ord(quals[i])-33) < options.baseq:
                    #make sure that quality is adjusted even if baseq is below threshold
                    if options.adjustbaseq:
                        if b == 'C' and a == 'T':
                            if options.cpg:
                                if i+1 >= readlen: break
                                if real_read[i+1] != 'G': continue

                            newprob= Newbaseq(i,ancient_model_deam,quals)
                            newphred=int(prob2phred(newprob))
                            newqual=chr(int(newphred)+33)                        
                            newquals=quals[0:i]+newqual+quals[(i+1):]

                        if b == 'G' and a == 'A':
                            if options.cpg:
                                if i+1 >= readlen: break
                                if real_read[::-1][i+1] != 'C': continue

                            newprob= Newbaseq(z,ancient_model_deam,qualsrev)
                            newphred=int(prob2phred(newprob))
                            newqual=chr(int(newphred)+33)                        
                            newquals=quals[0:i]+newqual+quals[(i+1):]
                    continue

                if options.deamination:
                    if b == 'C':
                        if options.cpg:
                            if i+1 >= readlen: break
                            if real_read[i+1] != 'G': continue
                        
                        thekey=b+a+str(i)
                        if thekey in mismatch_dict.keys():
                            addition = mismatch_dict[thekey]
                            addition += 1
                            mismatch_dict[thekey] = addition
                        else:
                            mismatch_dict[thekey] = 1
                        

                    if b == 'G':
                        if options.cpg:
                            if i+1 >= readlen: break
                            elif [z+1] >= readlen: break
                            if real_read[::-1][z+1] != 'C': continue
                        
                        thekey=b+a+str(z)
                        if thekey in mismatch_dict_rev.keys():
                            addition = mismatch_dict_rev[thekey]
                            addition += 1
                            mismatch_dict_rev[thekey] = addition
                        else:
                            mismatch_dict_rev[thekey] = 1
                    continue


                ##############
                # compute degradation score
                ##############
                if True:
                    if i >= readlen:continue
                    if b == 'C':
                        if options.cpg:
                            if i+1 >= readlen: break
                            if real_read[i+1] != 'G': continue
                        if a=='T': 
                            L_D = L_D * L_mismatch(i,ancient_model_deam,quals,options.polymorphism_ancient) 
                            L_M = L_M * L_mismatch(i,modern_model_deam,quals,options.polymorphism_contamination) 
                        
                            if options.adjustbaseq:
                                newprob= Newbaseq(i,ancient_model_deam,quals)
                                newphred=int(prob2phred(newprob))
                                newqual=chr(int(newphred)+33)
                                quals=quals[0:i]+newqual+quals[(i+1):]
                                #print(phred2prob(ord(quals[i])),newprob)
                                #print(ord(quals[i]),newphred)
                                #print(quals[i],newqual)
                                #print(quals[0:i],quals[i],quals[(i+1):])
                                #print(quals)
                            

                        

                        elif a=='C': 
                            L_D = L_D * L_match(i,ancient_model_deam,quals,options.polymorphism_ancient) 
                            L_M = L_M * L_match(i,modern_model_deam,quals,options.polymorphism_contamination) 

                    if b == 'G':
                        if options.cpg:
                            if i+1 >= readlen: break
                            if real_read[::-1][i+1] != 'C': continue
                        if a=='A': 
                            L_D = L_D * L_mismatch(z,ancient_model_deam,qualsrev,options.polymorphism_ancient) 
                            L_M = L_M * L_mismatch(z,modern_model_deam,qualsrev,options.polymorphism_contamination) 

                            if options.adjustbaseq:
                                newprob= Newbaseq(z,ancient_model_deam,qualsrev)
                                
                                newphred=int(prob2phred(newprob))
                                newqual=chr(int(newphred)+33)                        
                                newquals=quals[0:i]+newqual+quals[(i+1):]

                        elif a=='G': 
                            #try:
                            L_D = L_D * L_match(z,ancient_model_deam,qualsrev,options.polymorphism_ancient) 
                            L_M = L_M * L_match(z,modern_model_deam,qualsrev,options.polymorphism_contamination) 
                            #except IndexError:
                            #    print(line, file=stderr)


            LR= (math.log(L_D/L_M)  )
            quals=newquals    

        if options.adjustbaseq:
            if reverse:
                qualsp=quals[::-1]
            else:
                qualsp=quals
            line='\t'.join(col[0:10])+'\t'+qualsp+'\t'+'\t'.join(col[11:])

        ##############
        # add PMDS tag
        ##############
        if options.writesamfield == True:
            # remove DS field if present
            if DSfield==True:
                newline=''
                for col in line.split('\t'):
                    if 'DS:Z:' in col:
                        continue
                    else:
                        newline += col+'\t'
                line=newline.rstrip('\t')
            
            line=line.rstrip('\n')+'\t'+'DS:Z:'+str(round(LR,3))

        if options.printDS:
            print(L_D,'\t',L_M,'\t',L_D/L_M,'\t',LR) #,'\t',readlen,'\t',perc_identity,'\t',perc_identity*(math.log((L_D/L_M)))

        if options.dry:
            print(line.rstrip('\n'))
            continue
        
        if options.threshold > (-10000) or options.upperthreshold < (1000000): 

            if LR >= options.threshold and LR < options.upperthreshold:
                print(line.rstrip('\n'))
            else:
                excluded_threshold +=1

        if options.printalignments:
            if options.threshold > (-10000) or options.upperthreshold < (1000000):
                try:
                    LR= (math.log(L_D/L_M)  )
                except: continue
                if LR < options.threshold or LR >options.upperthreshold < (1000000):
                    continue

            quals1=''
            quals2=''            
            for q in quals:
                qnum=ord(q)-33
                if qnum <10:
                    quals1 +='0'
                    quals2+=str(qnum)
                else:
                    quals1+=str(qnum)[0]
                    quals2+=str(qnum)[1]
            #print(MD,cigar,reverse)
            #print(col[9])
            print(real_read)
            print(mismatch_string)
            print(real_ref_seq)
            print(quals)
            #print(quals1)
            #print(quals2)
            #print(col[10])
            print('')
        passed+=1
        if passed >= options.maxreads:break


    if options.stats:
        stats = """---------------------------------
        - excluded due to clipping: {clipexcluded}
        - excluded due to indels: {indelexcluded}
        - no MD field: {noMD}
        - no G or C in ref: {noGCexcluded}
        - total seqs: {passed}
        - excluded due to PMD score <{threshold}: {excluded_threshold}
        - passed seqs: {passed_seqs} 
        ---------------------------------
        """.format(
            clipexcluded=clipexcluded,
            indelexcluded=indelexcluded,
            noMD=noMD,
            noGCexcluded=noGCexcluded,
            passed=passed,
            threshold=int(options.threshold),
            excluded_threshold=excluded_threshold,
            passed_seqs=passed-excluded_threshold,
            )
        print(stats, file=stderr)


    if options.deamination:
        pairs=['CT','CA','CG','CC','GA','GT','GC','GG']
        itotaldict={}
        ztotaldict={}
        for i in range(0,options.range):
            itotal=0
            ztotal=0
            for p in pairs:
                thekey=p+str(i)
                try:
                    itotal += mismatch_dict[thekey]
                except KeyError: pass
                try:
                    ztotal += mismatch_dict_rev[thekey]
                except KeyError: pass
            itotaldict[i]=itotal
            ztotaldict[i]=ztotal

        print('z\t','\t'.join(pairs))

        for i in range(0,options.range):
            print(str(i)+'\t', end="")
            for p in pairs:
                thekey=p+str(i)
                if 'C' in p[0]:
                    try:
                        thecount=mismatch_dict[thekey]
                    except KeyError: 
                        print('0.00000\t', end="")
                        continue
                    thetotal=itotaldict[i]
                    frac=1.0*thecount/thetotal
                if 'G' in p[0]:
                    try:
                        thecount=mismatch_dict_rev[thekey]
                    except KeyError: 
                        print('0.00000\t', end="")
                        continue
                    thetotal=ztotaldict[i]
                    frac=1.0*thecount/thetotal
                print(str(round(frac,5))+'\t', end="")
            print('')


if __name__ == "__main__":
    options = parse_args()
    main()
