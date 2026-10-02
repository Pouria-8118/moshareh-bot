from abc import ABCMeta, abstractmethod


class StemmerI(metaclass=ABCMeta):
    """
    Minimal compatible implementation of NLTK's StemmerI.

    This is the interface Hazm's Stemmer inherits from.
    """

    @abstractmethod
    def stem(self, token):
        """
        Strip affixes from the token and return the stem.
        """
        raise NotImplementedError