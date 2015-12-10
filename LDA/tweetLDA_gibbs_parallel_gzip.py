
from __future__ import division
import numpy as np
import pyspark
from pyspark.mllib.clustering import LDA, LDAModel
from pyspark.mllib.linalg import Vectors
from operator import add
import matplotlib.pyplot as plt
import collections
from math import gamma
import time

import json
from dateutil import parser, tz
from datetime import datetime, timedelta
import utils
import re

from pyspark.sql import SQLContext, Row
import pyspark.sql.functions as sqlfunc

def make_json(tweet):
    ''' Get stringified JSOn from Kafka, attempt to convert to JSON '''
    try:
        return json.loads(tweet.decode('utf-8'))
    except:
        return "error"+str(tweet.decode('utf-8'))

def filter_tweets(item,pattern):
    ''' Filters out the tweets we do not want.  Filters include:
            * No retweets 
            * No geolocation or location field (do we really care about this?)
            * English language only
            * No tweets with links
                - We need to check both entities and media fields for this (is that true?)
    '''
    return (('delete' not in item.keys()) and
            ('retweeted_status' not in item.keys())                           and 
            (item['lang']=='en')                       and
            (len(item['entities']['urls'])==0)                   and
            ('media' not in item['entities'].keys()) and
            (re.search(pattern,item['text'],re.I) is not None)
           )

def get_relevant_fields(item):
    ''' Reduce the full set of metadata down to only those we care about, including:
            * timestamp
            * username
            * text of tweet 
            * hashtags
            * geotag coordinates (if any)
            * location (user-defined in profile, not necessarily current location)
    '''
    return (item['id'], 
            {"timestamp":  item['created_at'],
             "username":    item['user']['screen_name'],
             "text":        item['text'],
             "hashtags":    [el['text'] for el in item['entities']['hashtags']],
             "geotag":    item['geo'],
             "user_loc":    item['user']['location']
            }
           )

def update_tz(d,dtype):
    
    def convert_timezone(item):
        from_zone = tz.gettz('UTC')
        to_zone = tz.gettz('America/New_York')
        dt = parser.parse(item['timestamp'])
        utc = dt.replace(tzinfo=from_zone)
        return utc.astimezone(to_zone)
    
    if dtype == "sql":
        return Row(id=d[0], time=convert_timezone(d[1]))
    elif dtype == "pandas":
        return convert_timezone(d[1])


# JSON conversion above


def getTweet(string):
    substring = '"tweet"'
    matchs = []
    for ii in xrange(len(string)-len(substring)):
        if string[ii:ii+len(substring)] == substring:
            matchs.append(ii)
    assert len(matchs) > 0, "no tweet"
    start = matchs[0] + 8
    while string[start:start+10] != '"hashtags"':
        start = start + 1
    return string[matchs[0]+9:start-2]

def getLogLik(allWords,nTopics,wordTopicCounters,topicCounters,beta):
    uniqueWords = np.unique(allWords)
    nVocab = len(uniqueWords)
    logLik = nTopics*(logGamma2(nVocab*beta)-nVocab*logGamma2(beta))
    for ii in xrange(0,nTopics):
        logLik = logLik - logGamma2(topicCounters[ii]+nVocab*beta)
        assert topicCounters[ii] >= 0, "topic counter error"
        for jj in uniqueWords:
            logLik = logLik + logGamma2(wordTopicCounters[jj][ii]+beta)
            assert wordTopicCounters[jj][ii] >= 0, "word counter error"
    return logLik

def logGamma2(num):
    if num < 170:
        return np.log(gamma(num))
    else:
        num = num - 1
        return np.log(np.sqrt(2*np.pi*num)) + num*np.log(num/np.exp(1))

def findWord(wordArray,target):
    index = []
    for ii in xrange(0,len(wordArray)):
        if wordArray[ii] == target:
            index.append(ii)
    return index

def findWord2(words,target):
    index = []
    for ii in xrange(0,len(words)-len(target)):
        if words[ii:ii+len(target)] == target:
            index.append(ii)
    return index

def preProcessWords(texts):
   
    wordDocDict = {}
    wordDocDictNU = {}
    nDocs = len(texts)
    
    for ii in xrange(0,nDocs):
        textString = texts[ii].lower().split()
        for jj in xrange(0,len(textString)):
            if jj == 0:
                tempText = textString[jj][1:]
            elif jj == len(textString)-1:
                tempText = textString[jj][:-1]
            else:
                tempText = textString[jj]
            if tempText in wordDocDict:
                wordDocDict[tempText].add(ii)
                wordDocDictNU[tempText].append(ii)
            else:
                wordDocDict[tempText] = set([ii])
                wordDocDictNU[tempText] = [ii]
    uniqueWords = np.array(wordDocDict.keys())
    uniqueWordDocLabels = np.array(wordDocDict.values())
    nuWordDocLabels = np.array(wordDocDictNU.values())
    nDocPerWord = np.array(map(lambda x: len(x),uniqueWordDocLabels))
   
    # only keep words that appear in at least 5 tweets
    uniqueWords = uniqueWords[nDocPerWord > 4]
    nuWordDocLabels = nuWordDocLabels[nDocPerWord > 4]
    nInstances = np.array(map(lambda x: len(x),nuWordDocLabels))
   
    allWords = []
    docLabel = []

    f = open('stop_words.txt')
    stopWords = f.read()
    f.close()
    stopWords = stopWords.split()
   
    remW = set(stopWords+[''])
   
    filter1 = np.array([True]*len(uniqueWords))
    for ii in xrange(0,len(uniqueWords)):
        if uniqueWords[ii] in remW:
            filter1[ii] = False
   
    uniqueWords = uniqueWords[filter1]
    nuWordDocLabels = nuWordDocLabels[filter1]
    nInstances = nInstances[filter1]
   
    for ii in xrange(0,len(uniqueWords)):
        allWords = allWords + [uniqueWords[ii]]*len(nuWordDocLabels[ii])
        docLabel = docLabel + nuWordDocLabels[ii]
       
    return (np.array(allWords), np.array(docLabel))

def drawTopicInit(allWords,docLabel,nTopics,alpha,beta):
   
    vocab = np.unique(allWords)
    nVocab = len(vocab)
    wordTopicCounters = {ii:collections.Counter() for ii in vocab}
    docTopicCounters = {ii:collections.Counter() for ii in np.unique(docLabel)}
    topicCounters = {ii:0 for ii in xrange(0,nTopics)}
    docCounters = {ii:0 for ii in np.unique(docLabel)}
   
    topicVector = np.zeros(len(allWords))
   
    for ii in xrange(0,len(allWords)):
        currentWord = allWords[ii]
        currentDoc = docLabel[ii]
       
        probVector = np.zeros(nTopics)
        for jj in xrange(0,nTopics):
            probVector[jj] = (wordTopicCounters[currentWord][jj]+beta)/(topicCounters[jj] + nVocab*beta)
            probVector[jj] = probVector[jj]*(docTopicCounters[currentDoc][jj]+alpha)/(docCounters[currentDoc] + nTopics*alpha)
       
        probVector = probVector/sum(probVector)
        probCumSum = np.cumsum(probVector)
        randInt = np.random.uniform(0,1,1)

        currentTopic = sum(probCumSum < randInt)
        topicVector[ii] = currentTopic
       
        wordTopicCounters[currentWord][currentTopic] += 1
        docTopicCounters[currentDoc][currentTopic] += 1
        topicCounters[currentTopic] += 1
        docCounters[currentDoc] += 1 
   
    return topicVector, wordTopicCounters, docTopicCounters, topicCounters, docCounters

def drawTopic(wordIndex,allWords,topicLabel,docLabel,nTopics,wordTopicCounters, docTopicCounters, \
                                                                      topicCounters, docCounters,alpha,beta):
    nVocab = len(wordTopicCounters.keys())
    probVector = np.zeros(nTopics)
   
    currentWord = allWords[wordIndex]
    currentDoc = docLabel[wordIndex]
    currentTopic = topicLabel[wordIndex]
   
    for ii in xrange(0,nTopics):
        if ii == currentTopic:
            probVector[ii] = (wordTopicCounters[currentWord][ii]+beta-1)/(topicCounters[ii] + nVocab*beta - 1)
            probVector[ii] = probVector[ii]*(docTopicCounters[currentDoc][ii]+alpha-1)/(docCounters[currentDoc] + \
                                                                                        nTopics*alpha - 1)
        else:
            probVector[ii] = (wordTopicCounters[currentWord][ii]+beta)/(topicCounters[ii] + nVocab*beta)
            probVector[ii] = probVector[ii]*(docTopicCounters[currentDoc][ii]+alpha)/(docCounters[currentDoc] + \
                                                                                        nTopics*alpha)
                                                                                                                      
    probVector = probVector/sum(probVector)
    probCumSum = np.cumsum(probVector)
    randInt = np.random.uniform(0,1,1)
   
    newTopic = sum(probCumSum < randInt)
   
    if newTopic != currentTopic:
        wordTopicCounters[currentWord][newTopic] += 1
        wordTopicCounters[currentWord][currentTopic] -= 1
        docTopicCounters[currentDoc][newTopic] += 1
        docTopicCounters[currentDoc][currentTopic] -= 1
        topicCounters[newTopic] += 1
        topicCounters[currentTopic] -= 1
   
    return newTopic, wordTopicCounters, docTopicCounters, topicCounters

def verifyCounts(WordDocVec_OrderedSet):
    uniqueWords = WordDocVec_OrderedSet[3]
    topicLabel = WordDocVec_OrderedSet[5]
    allWords = WordDocVec_OrderedSet[10]
    allWordCountsS = WordDocVec_OrderedSet[6]
    
    for ii in uniqueWords:
        for jj in xrange(nTopics):
            if allWordCountsS[ii][jj] < sum((topicLabel == jj) & (allWords == ii)):
                print "sync outside counts: ",allWordCounts[ii][jj]," inside counts: ",allWordCountsS[ii][jj] ," present value: ",sum((topicLabel == jj) & (allWords == ii))
                asdf

def stationaryLDA(WordDocVec_OrderedPair):

    allWords = WordDocVec_OrderedPair[0]
    docLabel = WordDocVec_OrderedPair[1]
    nTopics = 50 
    uniqueWords = np.unique(allWords)
    uniqueDocs = np.unique(docLabel)
    nVocab = len(uniqueWords)
    nDocs = len(uniqueDocs)
   
    theta = np.zeros((nDocs,nTopics))
    phi = np.zeros((nTopics,nVocab))
   
    # just need allWords, docLabel, topicLabel
    alpha = 0.001
    beta = 0.01
   
    nIterations = 1
    count = 0
   
    topicLabel, wordTopicCounters, docTopicCounters, topicCounters, docCounters = \
                                                                    drawTopicInit(allWords,docLabel,nTopics,alpha,beta)
                                                                                              
    logLik = np.zeros(nIterations+1)
    logLik[0] = getLogLik(allWords,nTopics,wordTopicCounters,topicCounters,beta)
   
    while count < nIterations:
        for ii in xrange(0,len(allWords)):
            topic, wordTopicCounters, docTopicCounters, topicCounters = drawTopic(ii,allWords,\
                              topicLabel,docLabel,nTopics,wordTopicCounters, docTopicCounters, \
                                                                                  topicCounters, docCounters,alpha,beta)
            topicLabel[ii] = topic
        # update phi and theta here, calculate P(w|z)
        for ii in xrange(0,nTopics):
            sumCurr = topicCounters[ii]
            for jj in xrange(0,nVocab):
                phi[ii,jj] = (wordTopicCounters[uniqueWords[jj]][ii] + beta)/(sumCurr + nVocab*beta)
        for ii in xrange(0,nDocs):
            sumCurr = docCounters[uniqueDocs[ii]]
            for jj in xrange(0,nTopics):
                theta[ii,jj] = (docTopicCounters[uniqueDocs[ii]][jj] + alpha)/(sumCurr + nTopics*alpha)
        logLik[count+1] = getLogLik(allWords,nTopics,wordTopicCounters,topicCounters,beta)
        print "first time: ",logLik
        count = count + 1
    """
    for ii in uniqueWords:
        for jj in xrange(nTopics):
            if wordTopicCounters[ii][jj] != sum((topicLabel == jj) & (allWords == ii)):
                print "first time topic counts: ",wordTopicCounters[ii][jj] ," present value: ",sum((topicLabel == jj) & (allWords == ii))
                asdf
    """

    return (theta, phi, logLik, uniqueWords, uniqueDocs, topicLabel,\
                                            wordTopicCounters, topicCounters, docTopicCounters, docCounters,allWords,docLabel)

def stationaryLDA_post(WordDocVec_OrderedSet):

    theta = WordDocVec_OrderedSet[0]
    phi = WordDocVec_OrderedSet[1]
    logLik = WordDocVec_OrderedSet[2]
    uniqueWords = WordDocVec_OrderedSet[3]
    uniqueDocs = WordDocVec_OrderedSet[4]
    topicLabel = WordDocVec_OrderedSet[5]
    wordTopicCounters = WordDocVec_OrderedSet[6]
    topicCounters = WordDocVec_OrderedSet[7]
    docTopicCounters = WordDocVec_OrderedSet[8]
    docCounters = WordDocVec_OrderedSet[9]
    allWords = WordDocVec_OrderedSet[10]
    docLabel = WordDocVec_OrderedSet[11]

    nTopics = 50 

    """
    for ii in uniqueWords:
        for jj in xrange(nTopics):
            if wordTopicCounters[ii][jj] < sum((topicLabel == jj) & (allWords == ii)):
                print "post outside counts: ",allWordCounts[ii][jj]," inside counts: ",wordTopicCounters[ii][jj] ," present value: ",sum((topicLabel == jj) & (allWords == ii))
                asdf
    """
   
    # just need allWords, docLabel, topicLabel
    alpha = 0.001
    beta = 0.01
   
    nIterations = 1
    count = 0
    nVocab = len(uniqueWords)
    nDocs = len(uniqueDocs)
                                                                                         
    logLik = np.zeros(nIterations+1)
    logLik[0] = getLogLik(allWords,nTopics,wordTopicCounters,topicCounters,beta)

    while count < nIterations:
        for ii in xrange(0,len(allWords)):
            if wordTopicCounters[allWords[ii]][topicLabel[ii]] <= 0:
                print "word index: ", ii
                print "word: ", allWords[ii]
                print "topic label: ",topicLabel[ii]
                print "topic count: ", allWordCounts[allWords[ii]][topicLabel[ii]]
                print "value outside: ", allWordCounts[allWords[ii]]#[topicLabel[ii]]
                print "value inside: ", wordTopicCounters[allWords[ii]]#[topicLabel[ii]]
                asdf
            topic, wordTopicCounters, docTopicCounters, topicCounters = drawTopic(ii,allWords,\
                              topicLabel,docLabel,nTopics,wordTopicCounters, docTopicCounters, \
                                                                                  topicCounters, docCounters,alpha,beta)
            topicLabel[ii] = topic
        # update phi and theta here, calculate P(w|z)
        for ii in xrange(0,nTopics):
            sumCurr = topicCounters[ii]
            for jj in xrange(0,nVocab):
                phi[ii,jj] = (wordTopicCounters[uniqueWords[jj]][ii] + beta)/(sumCurr + nVocab*beta)
        for ii in xrange(0,nDocs):
            sumCurr = docCounters[uniqueDocs[ii]]
            for jj in xrange(0,nTopics):
                theta[ii,jj] = (docTopicCounters[uniqueDocs[ii]][jj] + alpha)/(sumCurr + nTopics*alpha)
        logLik[count+1] = getLogLik(allWords,nTopics,wordTopicCounters,topicCounters,beta)
        print "second time: ",logLik
        count = count + 1

    return (theta, phi, logLik, uniqueWords, uniqueDocs, topicLabel,\
                                            wordTopicCounters, topicCounters, docTopicCounters, docCounters,allWords,docLabel)

def synchronizeCounts(WordDocVec_OrderedSet,allWordCountsL,allTopicCountsL):
    
    uniqueWords = WordDocVec_OrderedSet[3]
    topicLabel = WordDocVec_OrderedSet[5]
    allWords = WordDocVec_OrderedSet[10]
    wordTopicCountCurr = WordDocVec_OrderedSet[6]
    # after extracting the 4 variables above for the current partition, compare the partition's 
    # word-topic counts dictionary, "wordTopicCountCurr", to the accumulated word topic counts "allWordCountsL"
    for ii in uniqueWords:
        for jj in xrange(nTopics):
            if allWordCountsL[ii][jj] < sum((topicLabel == jj) & (allWords == ii)):
                print "sync counts: ",allWordCountsL[ii][jj],"old counts: ",wordTopicCountCurr[ii][jj]," present value: ",sum((topicLabel == jj) & (allWords == ii))                
                asdf
      
    return (WordDocVec_OrderedSet[0],WordDocVec_OrderedSet[1],WordDocVec_OrderedSet[2],\
            WordDocVec_OrderedSet[3],WordDocVec_OrderedSet[4],WordDocVec_OrderedSet[5],\
            allWordCountsL.copy(),allTopicCountsL.copy(),WordDocVec_OrderedSet[8],WordDocVec_OrderedSet[9],\
            WordDocVec_OrderedSet[10],WordDocVec_OrderedSet[11])

sc = pyspark.SparkContext(appName = "Spark1")

f = open('search-terms.json','r')
j = f.readlines()
f.close()
searchj = json.loads(j[0])

search_terms = []
def get_vals(j):
    ''' Short recursive routine to pull out all search terms in search-terms.json '''
    if isinstance(j,dict):
        for j2 in j.values():
            get_vals(j2)
    else:
        search_terms.extend( j )
        
get_vals(searchj)

p = '|(\s|#|@)'.join(search_terms)

numPart = 5
nTopics = 10
numIterations = 500

#allTweets = sc.textFile('s3://cs205-final-project/tweets/gardenhose/gop/sep16/2015-09-16-20-30.gz')
allTweets = sc.textFile('2015-09-16-20-00.gz') 

"""
import gzip
with gzip.open('2015-09-16-20-00.gz','rb') as f:
    file_content = f.read()

allTweets = sc.parallelize(file_content).zipWithIndex().map(lambda x: (x[1],x[0])).filter(lambda x: x[0] < 10).cache()

print allTweets.collect()

asdf
"""

allTweets = (allTweets.map(make_json)
               .filter( lambda x: filter_tweets(x,p) )
               .map( get_relevant_fields )
               .map(lambda x: x[1]["text"])
               .map(lambda x: (len(x)%5,x))
               .partitionBy(numPart)
            )


allTweets = allTweets.groupByKey().mapValues(list).cache() # (partitionNum, ['tweet1','tweet2','tweet3',...])


tweets = allTweets.collect()
tweetRec = []
for ii in xrange(numPart):
    tweetRec = tweetRec + tweets[ii][1]

data = open('zipTweets.txt','w')
count = 0
for tweet in tweetRec:
    flag = True
    for char in tweet:
        if ord(char) > 128:
            flag = False
            break
    if flag:
        data.write("%s&&&&&" % tweet)
        count += 1
data.close()

print count

asdf

allTweets = allTweets.mapValues(preProcessWords).cache() # (partitionNum, (wordVec,docVec))


startT = time.time()
allTweets = allTweets.mapValues(stationaryLDA).cache() # (partitionNum, (theta,phi,logLik,uWords,uDocs,topicLabel,\
                                               # wordTopicCounters, topicCounters, docTopicCounters, docCounters, allWords, docLabel))

orderedPairs = allTweets.collect()

# accumulate word-topic and topic counts across partitions
allWordCounts = {}
allTopicCounts = {ii:0 for ii in xrange(0,nTopics)}
logLikMat = np.zeros((numIterations*2,numPart))
for ii in xrange(numPart):
    # current partition's word-topic counts dictionary
    currWordTopicCounter = orderedPairs[ii][1][6]
    logLikMat[0:2,ii] = orderedPairs[ii][1][2]
    for jj in currWordTopicCounter.keys():
        if jj not in allWordCounts:
            allWordCounts[jj] = collections.Counter()
        for kk in currWordTopicCounter[jj].keys():
            allWordCounts[jj][kk] += currWordTopicCounter[jj][kk]
            allTopicCounts[kk] += currWordTopicCounter[jj][kk]

#allWordCounts2 = allWordCounts.copy()
#testKey = "here" # allWordCounts.keys()[0]
#print "first time: ",allWordCounts[testKey]#[5]
#print orderedPairs[0][1][10][:3],orderedPairs[0][1][5][:3],orderedPairs[0][1][6][testKey]

# verify accumulated word-topic counts are greater than or equal to corresponding values in each parition
"""
for ii in xrange(numPart):
    currWordTopicCounter = orderedPairs[ii][1][6]
   
    uniqueWordsT = orderedPairs[ii][1][3]
    topicLabelT = orderedPairs[ii][1][5]
    allWordsT = orderedPairs[ii][1][10]
    
    for jj in uniqueWordsT:
        for kk in xrange(nTopics):
            if allWordCounts[jj][kk] < sum((topicLabelT == kk) & (allWordsT == jj)):
                print "initial total counts: ",allWordCounts[jj][kk] ," present value: ",sum((topicLabelT == kk) & (allWordsT == jj))
                asdf # break command
"""

# code currently break here in "synchronizeCounts", see "synchronizeCounts" above
#allTweets = allTweets.mapValues(lambda x: synchronizeCounts(x,allWordCounts.copy(),allTopicCounts.copy()))
allTweets = allTweets.mapValues(lambda x: (x[0],x[1],x[2],x[3],x[4],x[5],allWordCounts.copy(),\
                                            allTopicCounts.copy(),x[8],x[9],x[10],x[11])).cache()

allTweets.count()
allWordCounts0 = allWordCounts.copy()

for numIt in xrange(numIterations-1):
    print "iteration: ",numIt+1
    allTweets = allTweets.mapValues(stationaryLDA_post).cache()

    orderedPairs = allTweets.collect()
    allWordCounts = {}
    allTopicCounts = {ii:0 for ii in xrange(0,nTopics)}
    for ii in xrange(numPart):
        currWordTopicCounter = orderedPairs[ii][1][6]
        logLikMat[2*(numIt+1):2*(numIt+1)+2,ii] = orderedPairs[ii][1][2]
        for jj in currWordTopicCounter.keys():
            if jj not in allWordCounts:
                allWordCounts[jj] = collections.Counter()
            for kk in currWordTopicCounter[jj].keys():
                allWordCounts[jj][kk] += currWordTopicCounter[jj][kk]

    for ii in allWordCounts.keys():
        for jj in allWordCounts[ii].keys():
            allWordCounts[ii][jj] -= (numPart-1)*allWordCounts0[ii][jj]
    for ii in allWordCounts.keys():
        for jj in allWordCounts[ii].keys():
            allTopicCounts[jj] += allWordCounts[ii][jj]

    allWordCounts0 = allWordCounts.copy()
    allTweets = allTweets.mapValues(lambda x: (x[0],x[1],x[2],x[3],x[4],x[5],allWordCounts.copy(),\
                                            allTopicCounts.copy(),x[8],x[9],x[10],x[11])).cache()

uniqueWords = np.array(allWordCounts.keys())
nVocab = len(uniqueWords)
phi = np.zeros((nTopics,nVocab))
beta = 0.01
for ii in xrange(nTopics):
    sumCurr = allTopicCounts[ii]
    for jj in xrange(nVocab):
        phi[ii,jj] = (allWordCounts[uniqueWords[jj]][ii] + beta)/(sumCurr + nVocab*beta)

for ii in xrange(nTopics):
    #print uniqueWords[findWord(phi[ii,:]>.015,True)]
    print uniqueWords[np.argsort(phi[ii,:])[-10:]]

endT = time.time()
print "total time: ",endT-startT
plt.plot(logLikMat)
plt.show()

#allTweets = allTweets.mapValues(verifyCounts)
#allTweets.count()

#main extras
"""
    uniqueWordsT = orderedPairs[ii][1][3]
    topicLabelT = orderedPairs[ii][1][5]
    allWordsT = orderedPairs[ii][1][10]
    
    for jj in uniqueWordsT:
        for kk in xrange(nTopics):
            if currWordTopicCounter[jj][kk] != sum((topicLabelT == kk) & (allWordsT == jj)):
                print "main inside counts: ",currWordTopicCounter[jj][kk] ," present value: ",sum((topicLabelT == kk) & (allWordsT == jj))
                asdf
    """

# synchronize counts extras
"""
    allWordCountsS = {}
    allTopicCountsS = {ii:0 for ii in xrange(nTopics)}

    for jj in allWordCounts.keys():
        if jj not in allWordCountsS:
            allWordCountsS[jj] = collections.Counter()
        for kk in allWordCounts[jj].keys():
            allWordCountsS[jj][kk] = allWordCounts[jj][kk]
            allTopicCountsS[kk] += allWordCounts[jj][kk]
    for jj in xrange(nTopics):
        assert allTopicCountsS[jj] == allTopicCounts[jj], "topic counts different"
    for jj in allWordCounts.keys():
        for kk in allWordCounts[jj].keys():
            assert allWordCounts[jj][kk] == allWordCountsS[jj][kk], "word counts different"
    """






