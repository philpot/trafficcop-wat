#!/usr/bin/python

import sys
import argparse
import random
random.seed(10)
import cPickle as pickle
import json

from textblob.classifiers import NaiveBayesClassifier

from filetags import filetags, urlBodyTokens, canonUrl

from contextlib import contextmanager
import time
@contextmanager
def timeblock(label, verbose=False):
    start = time.clock()
    try:
        yield
    finally:
        end = time.clock()
        if verbose:
            print >> sys.stderr, ('  {} : {} seconds'.format(label, end - start))

def safediv(numerator, denominator, default=None):
    if denominator:
        return numerator/float(denominator)
    else:
        return default

def ci_extractor(document):
    """Only records positive features"""
    features = {}
    for token in document.split():
        features["contains_ci(%s)" % token.upper()] = True
    return features

def cs_extractor(document):
    """Only records positive features"""
    features = {}
    for token in document.split():
        features["contains_cs(%s)" % token] = True
    return features

def lookupFeatureExtractor(indicator):
    extractor_name = "%s_extractor" % indicator
    return globals().get(extractor_name, None)

# cl2 = NaiveBayesClassifier(test, feature_extractor=end_word_extractor)
# blob = TextBlob("I'm excited to try my new classifier.", classifier=cl2)
# blob.classify()

class PostClassifier(object):
    def __init__(self, positiveClass, trainSize=20, testSize=20, validateSize=20,
                 feature_extractor=None, indicator=None,
                 save=False, verbose=False, load=False, apply=False, type='text'):
        self.positiveClass = positiveClass
        self.trainSize = trainSize
        self.testSize = testSize
        self.validateSize = validateSize
        self.feature_extractor = feature_extractor
        self.indicator = indicator

        self.load = load
        self.save = save
        self.apply = apply
        self.inputType = type
        self.verbose = verbose

    def label(self, positiveClass):
        if self.verbose:
            print >> sys.stderr, "  loading and labeling texts for %s" % positiveClass
        self.labeledTexts = []
        for url,tags in filetags.iteritems():
            text = ' '.join(urlBodyTokens(canonUrl(url)))
            if positiveClass in tags:
                self.labeledTexts.append( (text, 'pos') )
            else:
                self.labeledTexts.append( (text, 'neg') )
        random.shuffle(self.labeledTexts)
        if self.verbose:
            print >> sys.stderr, "  finished labeling %d texts" % len(self.labeledTexts)
       
    def allocate(self):
        """Break up the entire set of labeled texts, typically in 80/10/10 ratio"""
        self.trainingSet = self.labeledTexts[0:self.trainSize]
        self.testSet = self.labeledTexts[self.trainSize:self.trainSize+self.testSize]
        self.validateSet = self.labeledTexts[self.trainSize+self.testSize:self.trainSize+self.testSize+self.validateSize]

    def buildClassifier(self):
        # positiveClass is a tag such as 'race'
        # race(pos) vs everything else(neg)
        with timeblock("training %s classifier" % self.positiveClass, self.verbose):
            if self.feature_extractor:
                cl = NaiveBayesClassifier(self.trainingSet, feature_extractor=self.feature_extractor)
            else:
                cl = NaiveBayesClassifier(self.trainingSet)
            self.classifier = cl
            if self.verbose:
                print >> sys.stderr, "  classifier %r" % cl

    def testClassifier(self):
        tp = 0
        tn = 0
        fp = 0
        fn = 0
        for (text, label) in self.testSet:
            prediction = self.classifier.classify(text)
            if label == 'pos' and prediction == 'pos':
                tp +=1
            elif label == 'neg' and prediction == 'neg':
                tn +=1
            elif label == 'pos' and prediction == 'neg':
                fn += 1
            elif label == 'neg' and prediction == 'pos':
                fp += 1
            else:
                raise Exception
        precision = safediv(tp, tp+fp)
        recall = safediv(tp, tp+fn)
        f1 = safediv(2*tp, 2*tp + fp + fn)
        accuracy = self.classifier.accuracy(self.testSet)
        if self.verbose:
            print >> sys.stderr, """  positiveClass: %s
  True Positive: %s
  True Negative: %s
  False Positive: %s
  False Negative: %s
  Precision: %s
  Recall: %s
  F1: %s
  Accuracy: %s""" % (self.positiveClass, tp, tn, fp, fn, precision, recall, f1, accuracy)

    def classifierFilename(self, positiveClass=None, indicator=None):
        positiveClass = positiveClass or self.positiveClass
        indicator = indicator or self.indicator
        if indicator:
            return 'data/classifier/%s_%s_classifier.pickle' % (positiveClass, indicator)
        else:
            return 'data/classifier/%s_default_classifier.pickle' % (positiveClass)

    def saveClassifier(self):
        with timeblock("saving %s %s classifier" % (self.positiveClass, self.indicator), self.verbose):
            with open(self.classifierFilename(), 'wb') as f:
                if self.verbose:
                    print >> sys.stderr, "  saving object %s of type %s to %s" % (self.classifier, type(self.classifier), self.classifierFilename())
                pickle.dump(self.classifier, f)

    def loadClassifier(self, classifierName, indicator):
        with timeblock("loading %s %s classifier" % (classifierName, indicator), self.verbose):
            with open(self.classifierFilename(), 'rb') as f:
                self.classifier = pickle.load(f)
                self.positiveClass = classifierName
                self.indicator = indicator

    def applyClassifier(self, input):
        classifierName = self.positiveClass
        indicator = self.indicator
        if input == '-':
            # special case, read from stdin
            input = sys.stdin.read()

        text = input

        if self.inputType == 'html':
            from pymod.htmlextract import extract_text
            text = extract_text(text)

        with timeblock("applying %s %s classifier" % (classifierName, indicator), self.verbose):
            prob_dist = self.classifier.prob_classify(text)
            result = {"input": input,
                      "class": self.positiveClass,
                      "prob": prob_dist.prob("pos")}
            return result

pc = None

def main(argv=None):
    '''this is called if run from command line'''
    parser = argparse.ArgumentParser()
    parser.add_argument('-n','--name','--positive', required=True, help='name, tag of positive class',
                        choices=('age','agency', 'healthspa', 'multi', 'race', 'typical', 'offtopic'))
    parser.add_argument('-l','--load', required=False, help='load', action='store_true')
    parser.add_argument('-s','--save', required=False, help='save', action='store_true')
    parser.add_argument('-v','--verbose', required=False, help='verbose', action='store_true')
    parser.add_argument('-i','--indicator','--featureset','--tokenizer', required=False, help='indicator', default='cs')
    parser.add_argument('-t','--type', required=False, default='text',
                        help='input file type', choices=('text', 'html'))
    parser.add_argument('--train', required=False, help='training size', default=800, type=int)
    parser.add_argument('--test', required=False, help='test set size', default=100, type=int)
    parser.add_argument('--validate', required=False, help='validation set size', default=100, type=int)
    parser.add_argument('--apply', required=False, help='apply')
    args=parser.parse_args()

    positiveClass = args.name
    indicator = args.indicator

    if args.verbose:
        print >> sys.stderr, "INITIALIZING"
    feature_extractor=lookupFeatureExtractor(indicator)
    global pc
    pc = PostClassifier(positiveClass, trainSize=args.train, testSize=args.test, validateSize=args.validate, 
                        indicator=indicator, feature_extractor=feature_extractor,
                        load=args.load, save=args.save, apply=args.apply, 
                        type=args.type, verbose=args.verbose)
    pc.label(pc.positiveClass)
    pc.allocate()
    if args.load:
        if pc.verbose:
            print >> sys.stderr, "LOADING"
        pc.loadClassifier(pc.positiveClass, pc.indicator)
    else:
        if pc.verbose:
            print >> sys.stderr, "BUILDING"
        pc.buildClassifier()
    if args.test:
        if pc.verbose:
            print >> sys.stderr, "TESTING"
        pc.testClassifier()
    if args.save:
        if pc.verbose:
            print >> sys.stderr, "SAVING"
        pc.saveClassifier()
    if args.validate:
        if pc.verbose:
            print >> sys.stderr, "VALIDATING"
            print >> sys.stderr, "NOT IMPLEMTED YET"
    if args.apply:
        if pc.verbose:
            print >> sys.stderr, "APPLYING"
        result = pc.applyClassifier(pc.apply)
        print >> sys.stdout, json.dumps(result, indent=4)


# call main() if this is run as standalone
if __name__ == "__main__":
    sys.exit(main())

"""
def accuracy(classifier, gold):
    results = classifier.classify_many([fs for (fs,l) in gold])
    correct = [l==r for ((fs,l), r) in zip(gold, results)]
    if correct:
        return float(sum(correct))/len(correct)
    else:
        return 0
"""
