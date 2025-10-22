#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Extract demo data from the sol file
# Usage: python sol_to_demo.py
# Disable "Prevent writing to disk" in libTAS to obtain TASed sol file

# Credits: SolReader class is taken from NHigh by jg9000 (+ modified)


import sys
import struct

SOL_FILE_LOCATION = 'docker_volume/n_tas.sol'


class SolReader(object):
    def __init__(self):
        self.readFuncs ={
            0: self.readNumber,
            1: self.readBool,
            2: self.readStr,
            3: self.readObj,
            5: self.readNull,
            6: self.readUndef,
            8: self.readArray,
            #10: self.readRawArr,
            #11: self.readDate,
            #13: self.readObjM,
            #15: self.readObjXML,
            #16: self.readCustomClass,
        }

    def readFromFile(self, size):
        ret = self.f.read(size)
        if len(ret) < size:
            raise EOFError()
        return ret
        
    def readStr(self):
        length, = struct.unpack('>H',self.readFromFile(2))
        if length==0:
            return ''
        s = self.readFromFile(length)
        return s.decode('utf-8')

    def readSol(self, f):
        ret = {}
        try:
            self.f = f
            self.readFromFile(2) #header?
            datasize, = struct.unpack('>L',self.readFromFile(4)) #datasize == filesize-6
            self.readFromFile(4) #filetype=='TCSO' ?
            self.readFromFile(6) #??
            self.readStr() #the .sol name == n_v14b_userdata
            self.readFromFile(4) #??

            while True:
                name = self.readStr()
                val = self.readValue()
                ret[name] = val
                self.readFromFile(1) # == 0
        except EOFError:
            pass
        except (ValueError, TypeError, struct.error):
            raise NHighError('.sol file contains invalid format')
        return ret

    def readNumber(self):
        val, = struct.unpack('>d', self.readFromFile(8))
        return val

    def readBool(self):
        return bool(ord(self.readFromFile(1)))

    def readObj(self):
        ret = {}
        while True:
            name = self.readStr()
            if not name: break
            val = self.readValue()
            ret[name] = val
        self.readFromFile(1) # ==9
        return ret

    def readArray(self):
        length, = struct.unpack('>L',self.readFromFile(4))
        last = -1
        ret = []
        while True:
            name = self.readStr()
            if not name: break
            try:
                now = int(name)
            except ValueError:
                raise NHighError('.sol File contains invalid array object')
            if now != last+1:
                raise NHighError('.sol File contains invalid array object')
            last = now
            ret.append(self.readValue())
        if last != length-1:
            raise NHighError('.sol File contains invalid array object')
        self.readFromFile(1) # ==9
        return ret

    def readNull(self):
        return None

    def readUndef(self):
        return None

    def readValue(self):
        typ = ord(self.readFromFile(1))
        func = self.readFuncs.get(typ)
        if func:
            return func()
        else:
            raise NHighError('.sol File contains unrecognized objects')


def readSolFile():
    filename = SOL_FILE_LOCATION
    if not filename:
        raise NHighError('.sol file not found')
    try:
        f = open(filename, 'rb')
        try:
            return SolReader().readSol(f)
        finally:
            f.close()
    except (IOError,OSError):
        raise NHighError('Error reading .sol file')

##############


def calcTotalScores(solData):
    totalEpisodeScore = 0
    totalLevelScore = 0
    try:
        for ep in xrange(100, NUM_EPISODES+100):
            epData = solData['persBest'][ep]
            totalEpisodeScore += int(epData['ep']['score'])
            for lvl in xrange(5):
                totalLevelScore += int(epData['lev'][lvl]['score'])
    except (KeyError,TypeError):
        raise NHighError('.sol data is incomplete')
    return (totalLevelScore, totalEpisodeScore)

def findUnsubmittedTop20(solData, hsTable):
    '''Returns: (player, results)
    where results is a list of tuples (ep_num, lvl_num, rank, unsubmitted_score, old_rank, old_entry)
    '''
    ret = []
    player = unicode2str(solData['username'])
    pllower = player.lower()
    try:
        for ep in xrange(100, 100+NUM_EPISODES):
            epSolData = solData['persBest'][ep]
            solScores = [0]*6
            for lvl in xrange(5):
                solScores[lvl] = int(epSolData['lev'][lvl]['score'])
            solScores[5] = int(epSolData['ep']['score'])
            
            epHSData = hsTable.table[ep]
            for lvl in xrange(6):
                solScore = solScores[lvl]
                lvlHSData = epHSData[lvl]
                for rank,entry in enumerate(lvlHSData):
                    if entry.score == 0:
                        break
                    if entry.score < solScore:
                        oldEntry = None
                        oldRank = None
                        for r, en in enumerate(lvlHSData):
                            if en.name.lower() == pllower:
                                oldEntry = en
                                oldRank = r
                                break
                        ret.append((ep, lvl, rank, solScore, oldRank, oldEntry))
                        break
                    if entry.name.lower() == pllower:
                        break
        return (player, ret)
    except (KeyError,TypeError):
        raise NHighError('.sol data is incomplete')


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} LEVEL")
        sys.exit(1)
    episode = int(sys.argv[1].split("-")[0])
    level = int(sys.argv[1].split("-")[1])
    solData = readSolFile()
    print(solData['persBest'][episode]['lev'][level]['demo'])
