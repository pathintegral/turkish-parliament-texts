import codecs

import logging

from gensim.corpora.textcorpus import TextCorpus
from gensim.corpora.dictionary import Dictionary

from collections import defaultdict as dd

from utils import tokenize, print_err

from six import itervalues, iteritems

logger = logging.getLogger(__name__)

class TbmmCorpus(TextCorpus):

    def __init__(self, input=None, dictionary=None, metadata=False, character_filters=None,
                 tokenizer=None, token_filters=None,
                 config=None):
        super().__init__(input, dictionary, metadata, character_filters, tokenizer, token_filters)

        self.documents = {}
        self.documents_metadata = {}

        self.metadata2description = {}

        self.documents_word_counts = {}

        self.dictionary.debug = True

        self.config = config

    @staticmethod
    def filter_extremes(dictionary_object, no_below=5, no_above=0.5, keep_n=100000, keep_tokens=None):
        """
        Filter out tokens that appear in

        1. less than `no_below` documents (absolute number) or
        2. more than `no_above` documents (fraction of total corpus size, *not*
           absolute number).
        3. if tokens are given in keep_tokens (list of strings), they will be kept regardless of
           the `no_below` and `no_above` settings
        4. after (1), (2) and (3), keep only the first `keep_n` most frequent tokens (or
           keep all if `None`).

        After the pruning, shrink resulting gaps in word ids.

        **Note**: Due to the gap shrinking, the same word may have a different
        word id before and after the call to this function!
        """
        assert isinstance(dictionary_object, Dictionary), "The object must be an instance of Dictionary"
        no_above_abs = int(
            no_above * dictionary_object.num_docs)  # convert fractional threshold to absolute threshold

        # determine which tokens to keep
        if keep_tokens:
            keep_ids = [dictionary_object.token2id[v] for v in keep_tokens if v in dictionary_object.token2id]
            good_ids = (
                v for v in itervalues(dictionary_object.token2id)
                if no_below <= dictionary_object.dfs.get(v, 0) <= no_above_abs or v in keep_ids
            )
        else:
            good_ids = (
                v for v in itervalues(dictionary_object.token2id)
                if no_below <= dictionary_object.dfs.get(v, 0) <= no_above_abs
            )
        good_ids = sorted(good_ids, key=dictionary_object.dfs.get, reverse=True)
        if keep_n is not None:
            good_ids = good_ids[:keep_n]
        bad_words = [(dictionary_object[idx], dictionary_object.dfs.get(idx, 0)) for idx in
                     set(dictionary_object).difference(good_ids)]
        logger.info("discarding %i tokens: %s...", len(dictionary_object) - len(good_ids), bad_words[:10])
        logger.info(
            "keeping %i tokens which were in no less than %i and no more than %i (=%.1f%%) documents",
            len(good_ids), no_below, no_above_abs, 100.0 * no_above
        )

        logger.info("resulting dictionary: %s", dictionary_object)
        return good_ids, (len(dictionary_object) - len(good_ids))

    @staticmethod
    def filter_tokens(dictionary_object, bad_ids=None, good_ids=None, compact_ids=True):
        """
        Remove the selected `bad_ids` tokens from all dictionary mappings, or, keep
        selected `good_ids` in the mapping and remove the rest.

        `bad_ids` and `good_ids` are collections of word ids to be removed.
        """
        assert isinstance(dictionary_object, Dictionary), "The object must be an instance of Dictionary"
        if bad_ids is not None:
            bad_ids = set(bad_ids)
            dictionary_object.token2id = {token: tokenid for token, tokenid in iteritems(dictionary_object.token2id) if
                                          tokenid not in bad_ids}
            dictionary_object.dfs = {tokenid: freq for tokenid, freq in iteritems(dictionary_object.dfs) if
                                     tokenid not in bad_ids}
        if good_ids is not None:
            good_ids = set(good_ids)
            dictionary_object.token2id = {token: tokenid for token, tokenid in iteritems(dictionary_object.token2id) if
                                          tokenid in good_ids}
            dictionary_object.dfs = {tokenid: freq for tokenid, freq in iteritems(dictionary_object.dfs) if
                                     tokenid in good_ids}
        if compact_ids:
            dictionary_object.compactify()

    def add_document(self, document, filepath):
        self.dictionary.add_documents([document],
                                      prune_at=None)
        self.documents[len(self.documents)+1] = self.dictionary.doc2idx(document)

        self.documents_metadata[len(self.documents)] = {
            'filepath': filepath
        }

        if len(self.documents) % 100 == 0:
            print_err("n_documents: %d" % len(self.documents))
            good_ids, n_removed = TbmmCorpus.filter_extremes(self.dictionary, no_below=0, no_above=1, keep_n=2000000)
            # do the actual filtering, then rebuild dictionary to remove gaps in ids
            TbmmCorpus.filter_tokens(self.dictionary, good_ids=good_ids, compact_ids=False)

            logger.info("tbmmcorpus rebuilding dictionary, shrinking gaps")

            # build mapping from old id -> new id
            idmap = dict(zip(sorted(itervalues(self.dictionary.token2id)), range(len(self.dictionary.token2id))))

            # reassign mappings to new ids
            self.dictionary.token2id = {token: idmap[tokenid] for token, tokenid in iteritems(self.dictionary.token2id)}
            self.dictionary.id2token = {}
            self.dictionary.dfs = {idmap[tokenid]: freq for tokenid, freq in iteritems(self.dictionary.dfs)}

            if n_removed:
                logger.info("Starting to remap word ids in tbmmcorpus documents hashmap")
                # def check_and_replace(x):
                #     if x in idmap:
                #         return x
                #     else:
                #         return -1
                for idx, (doc_id, document) in enumerate(self.documents.items()):
                    if idx % 1000 == 0:
                        logger.info("remapping: %d documents finished" % idx)
                    # self.documents[doc_id] = [check_and_replace(oldid) for oldid in document]
                    self.documents[doc_id] = [idmap[oldid] for oldid in document if oldid in idmap]

    def getstream(self):
        return super().getstream()

    def preprocess_text(self, text):
        return tokenize(text)

    def get_texts(self):
        if self.metadata:
            for idx, (documentno, document_text_in_ids) in enumerate(self.documents.items()):
                if idx % 1000 == 0:
                    print_err("get_texts:", documentno)
                document_text = [self.dictionary[id] for id in document_text_in_ids]
                yield self.preprocess_text(" ".join(document_text)), \
                      (documentno, self.documents_metadata[documentno])
        else:
            for idx, (documentno, document_text_in_ids) in enumerate(self.documents.items()):
                if idx % 1000 == 0:
                    print_err("get_texts:", documentno)
                document_text = [self.dictionary[id] for id in document_text_in_ids]
                yield self.preprocess_text(" ".join(document_text))

    def __len__(self):
        return len(self.documents)

    def __iter__(self):
        """The function that defines a corpus.

        Iterating over the corpus must yield sparse vectors, one for each document.
        """
        if self.metadata:
            for text, metadata in self.get_texts():
                yield self.dictionary.doc2bow(text, allow_update=False), metadata
        else:
            for text in self.get_texts():
                yield self.dictionary.doc2bow(text, allow_update=False)

    def save_tbmm_corpus(self, fname):
        # example code:
        # logger.info("converting corpus to ??? format: %s", fname)
        with codecs.open(fname, 'w', encoding='utf-8') as fout:
            for ((doc_id, document), (doc_id, metadata)) in zip(self.documents.items(), self.documents_metadata.items()):  # iterate over the document stream
                fmt = " ".join([str(x) for x in document])  # format the document appropriately...
                fout.write("%d %s %s\n" % (doc_id, metadata['filepath'], fmt))  # serialize the formatted document to disk

        self.dictionary.save(fname + ".vocabulary")
        self.dictionary.save_as_text(fname + ".vocabulary.txt")

    def load_tbmm_corpus(self, fname):
        with codecs.open(fname, 'r', encoding='utf-8') as f:
            line_idx = 0
            line = f.readline()
            while line:
                tokens = line.strip().split(" ")
                metadata = {}
                doc_id = int(tokens[0])
                metadata['filepath'] = tokens[1]
                document = [int(t) for t in tokens[2:]]

                self.documents[doc_id] = document
                self.documents_metadata[doc_id] = metadata

                line_idx += 1
                if line_idx % 100 == 0:
                    logger.info("loaded %d documents" % line_idx)

                line = f.readline()

        self.dictionary = self.dictionary.load_from_text(fname + ".vocabulary.txt")

    @staticmethod
    def get_document_topics(corpus, lda, document):
        """

        :type lda: gensim.models.ldamodel.LdaModel
        :param lda:
        :param document: we expect ids
        :return:
        """

        document_bow = TbmmCorpus.doc2bow_from_word_ids(document)

        return document_bow, lda.get_document_topics(document_bow, per_word_topics=False)

    @staticmethod
    def doc2bow_from_word_ids(document):
        counter = dd(int)
        for word_idx in document:
            counter[word_idx] += 1
        document_bow = sorted(iteritems(counter))
        return document_bow


    def generate_word_counts(self):

        for idx, (doc_id, document) in enumerate(self.documents.items()):
            self.documents_word_counts[doc_id] = TbmmCorpus.doc2bow_from_word_ids(document)

            if idx % 1000 == 0:
                logger.info("word_counts: %d documents" % idx)

    def query_word_count_across_all_documents(self, target_word_id):

        counts = {}

        for idx, (doc_id, document_word_counts) in enumerate(self.documents_word_counts.items()):
            target_freq_for_this_document = \
                [freq for word_id, freq in document_word_counts if word_id == target_word_id]
            if target_freq_for_this_document:
                target_freq_for_this_document = target_freq_for_this_document[0]

                filepath = self.documents_metadata[doc_id]['filepath']

                tokens = self.metadata2description[filepath]

                main_type = tokens[0]
                second_type_and_term = tokens[1]
                pdf_filename = tokens[2]

                if main_type not in counts:
                    counts[main_type] = dict()
                    counts[main_type][second_type_and_term] = dict()
                    counts[main_type][second_type_and_term][pdf_filename] = target_freq_for_this_document
                else:
                    if second_type_and_term not in counts[main_type]:
                        counts[main_type][second_type_and_term] = dict()
                        counts[main_type][second_type_and_term][
                            pdf_filename] = target_freq_for_this_document
                    else:
                        counts[main_type][second_type_and_term][
                            pdf_filename] = target_freq_for_this_document

            if idx % 1000 == 0:
                logger.info("%d documents scanned for word_id")
        return counts




    def prepare_metadata_to_description_dictionary(self):
        """
        The entry in metadata dictionary
        kurucu-meclis/milli-birlik-komitesi-d00/mbk_00002fih/
        Corresponding description is in this CSV file
        resources/urls/kurucu-meclis/milli-birlik-komitesi-d00.csv
        as this line
        "https://www.tbmm.gov.tr/tutanaklar/TUTANAK/MBK_/d00/c002/mbk_00002fih.pdf", 2. Cilt Fihristi
        :return:
        """

        assert self.config, "we need to know where the resources/urls directory is"

        import csv
        import glob
        import re

        for idx, filepath in enumerate(glob.iglob(self.config["resources_dir"] + '/**/*.csv', recursive=True)):
            m = re.match(r"{resources_dir}([^/]+)/([^/]+).csv".format(resources_dir=self.config["resources_dir"]),
                         filepath)
            if m:
                first_level_dir = m.group(1)
                csv_filename = m.group(2)
                donem_no = csv_filename.split("-")[-1]
                with open(filepath, mode="r", newline='') as f:
                    rows = list(csv.reader(f, delimiter=',', quotechar='"'))
                    for row in rows[1:]:
                        m_url = re.match(r".*/([^/]+).pdf$", row[0])
                        if m_url:
                            pdf_filename = m_url.group(1)
                            self.metadata2description[
                                "/".join([first_level_dir, csv_filename, pdf_filename, ''])] \
                                = [first_level_dir, csv_filename, donem_no, pdf_filename,
                                   row[1].strip()]
                        else:
                            logger.warning("incompatible url: " + row[0])


if __name__ == "__main__":

    import configparser

    config_parser = configparser.ConfigParser()
    config_parser.read("config.ini")
    config = config_parser['default']

    from tbmmcorpus import TbmmCorpus

    corpus = TbmmCorpus(metadata=True, config=config)

    corpus.prepare_metadata_to_description_dictionary()

    # corpus.load_tbmm_corpus("tbmm_corpus.mm")
    #
    # from gensim.models.ldamodel import LdaModel
    #
    # lda = LdaModel.load("tbmm_lda.model")




