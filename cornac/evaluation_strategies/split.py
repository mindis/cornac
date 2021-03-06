# -*- coding: utf-8 -*-

"""
@author: Aghiles Salah
"""

import numpy as np
import scipy.sparse as sp
from ..utils.util_functions import which_
from .evaluation_strategy import EvaluationStrategy
import sys


class Split(EvaluationStrategy):
    """Evaluation Strategy Split. 

    Parameters
    ----------
    data: scipy sparse matrix, required
        The user-item preference matrix.

    prop_test: float, optional, default: 0.2
        The propotion of the test set, \
        if > 1 then it is treated as the size of the test set.

    prop_validation: float, optional, default: 0.0
        The propotion of the validation set, \
        if > 1 then it is treated as the size of the validation set.

    good_rating: float, optional, default: 1
        The minimum value that is considered to be a good rating, \
        e.g, if the ratings are in {1, ..., 5}, then good_rating = 4.

    data_train: ..., optional, default: None
        The training data.

    data_validation: ..., optional, default: None
        The validation data.

    data_test: ..., optional, default: None
        The test data.

    index_train: 1d array, optional, default: None
        The indexes of training data (starting from 0).

    index_validation: 1d array, optional, default: None
        The indexes of validation data (starting from 0).

    index_test: 1d array, optional, default: None
        The indexes of test data (starting from 0).

    data_train_bin: ..., default: None
        The binary training data.

    data_validation_bin: ..., default: None
        The binary validation data.

    data_test_bin: ..., default: None
        The binary test data.
    """
    
    def __init__(self, data,prop_test=0.2,prop_validation=0.0,good_rating = 1., data_train=None, data_validation=None, data_test=None,index_train = None,index_validation = None,index_test = None):
        EvaluationStrategy.__init__(self, data,good_rating = good_rating, data_train=data_train, data_validation=data_validation, data_test=data_test)
        self.prop_test = prop_test
        self.prop_validation = prop_validation
        #may be move these attributes to the parent class 
        self.index_train = index_train
        self.index_validation = index_validation
        self.index_test = index_test
        #Additional attributes, 
        self.split_ran  = False          #check whether the data is already split or not           
        self.rank_met = False            #Check wether there is no ranking metric to save some computation
        
    
    def train_test_split_(self):

        print("Spliting the data")
        n = self.data_nnz
        if self.prop_test > 1:
            print("\'prop_test\'>1 and is treated as the size of the test data")
            if self.prop_test > n:
                sys.exit("\'prop_test\' is greater than the number of users")
            else:
                size_train = n - int(self.prop_test)
        else:
            size_train = int(np.round((1-self.prop_test)*n))
    
        index_train = np.random.choice(n, size=size_train,replace=False,p=None) #sample without replacement
        index_test = np.where(np.invert(np.in1d(np.array(range(n)), index_train)))[0] #index_test are the indices which are not in index_train
    
        return index_train, index_test
    
    
    

    def run_(self):
    
        #Building train and test sets
        
        if self._data_train is None or self._data_test is None:
            
            if self.index_train is None or self.index_test is None:
                self.index_train, self.index_test = self.train_test_split_() 
      
            #preparing training set, creating the training sparse matrix 
            print("Preparing training data")
            train_data = self.data[self.index_train,:]
            id_train_users = np.array(train_data[:,0],dtype='int64').flatten() 
            id_train_items = np.array(train_data[:,1],dtype='int64').flatten() 
            ratings_train = np.array(train_data[:,2],dtype='float64').flatten()
            self._data_train = sp.csc_matrix((ratings_train, (id_train_users,id_train_items)),shape=(self.data_nrows, self.data_ncols))
            del(id_train_users,id_train_items,ratings_train)
            self._data_train.eliminate_zeros()
            self._data_train = sp.csc_matrix(self._data_train)
        
        
            #preparing test set
            print("Preparing test data")
            test_data = self.data[self.index_test,:]
            id_test_users = np.array(test_data[:,0],dtype='int64').flatten()
            id_test_items = np.array(test_data[:,1],dtype='int64').flatten()
            ratings_test  = np.array(test_data[:,2],dtype='float64').flatten()
            self._data_test = sp.csc_matrix((ratings_test, (id_test_users,id_test_items)),shape=(self.data_nrows, self.data_ncols))  
            self._data_test.eliminate_zeros()
            self._data_test = sp.csc_matrix(self.data_test)        
        
         
        #Binary train data, useful to get some stats, such as the number of ratings per user
        self._data_train_bin = self._data_train.copy()  # always use copy() with sparse matrices affectations (the assignement is done in variables) 
        self._data_train_bin.data = np.full(len(self._data_train_bin.data),1)
        #update this binarization process
      
      
        #Binary test data, useful for ranking and top@M evaluation
        self._data_test_bin = self._data_test.copy()
        self._data_test_bin.data[which_(self.data_test_bin.data,'<',self.good_rating)] = 0.       
        self._data_test_bin.eliminate_zeros()    
        self._data_test_bin.data = np.full(len(self.data_test_bin.data),1)
        self.split_ran = True


    #This function is callable from the experiement class so as to run an experiment 
    def run_exp(self, model, metrics):
        #check wether we have at least one ranking metric
        for mt in metrics:
            if mt.type == 'ranking':
                self.rank_met = True
                break

        
        if not self.split_ran:
            self.run_()
        
        
        model.fit(self.data_train)
        print("Starting evaluation")
        res = sp.csc_matrix((self.data_test.shape[0],len(metrics)+1)) #this matrix will contain the evaluation results for each user
    
        #evaluation is done user by user to avoid memory errors on large datasets. 
        #loops are inefficent in python, this part should be re-implement in cython or c/c++"""
        nb_processed_users = 0
        for u in range(self.data_test.shape[0]):
            if not np.sum(self.data_test_bin[u,:]): #users with 0 heldout items should not be consider in the evaluation
                nb_processed_users +=1
            else:
                pred_u = model.predict(index_user=u)
                pred_u[which_(self.data_train[u,:].todense().A1,">",0)] = 0.   #remove known ratings #.A1 allows to flatten a dense matrix
                if self.rank_met:
                    rec_list_u = (-pred_u).argsort()  #ordering the items (in decreasing order) according to the predictions
                
                #computing the diffirent metrics
                idx = 0
                for mt in metrics:
                    if mt.type == 'ranking':
                        res[u,idx] = mt.compute(data_test = self.data_test_bin[u,:].todense().A1, reclist=rec_list_u)
                    else:
                        res[u,idx] = mt.compute(data_test = self.data_test[u,:].todense().A1, prediction=pred_u)
                    idx = idx + 1
                res[u,len(metrics)] = 1 # This column indicates whether a user have been preprocessed
                nb_processed_users +=1
            if nb_processed_users % 1000 == 0:
                print(nb_processed_users,"processed users")
        #computing the average results 
        res_avg = res[which_(res[:,len(metrics)].todense().A1,">",0),:].mean(0).A1   # of type array
        res_tot = {"ResAvg":res_avg[0:len(metrics)],"ResPerUser": res}
        return res_tot   