from abc import ABC, abstractmethod


class TokenizerI(ABC):
    """
    Minimal compatible implementation of NLTK's TokenizerI.

    This is the interface Hazm's WordTokenizer inherits from.
    """

    @abstractmethod
    def tokenize(self, s: str) -> list[str]:
        raise NotImplementedError

    def tokenize_sents(self, strings: list[str]) -> list[list[str]]:
        return [self.tokenize(s) for s in strings]

    def span_tokenize(self, s: str):
        raise NotImplementedError

    def span_tokenize_sents(self, strings: list[str]):
        for s in strings:
            yield list(self.span_tokenize(s))