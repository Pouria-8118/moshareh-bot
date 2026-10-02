from workers import Response, WorkerEntrypoint

from hazm import Normalizer
from rapidfuzz import fuzz


class Default(WorkerEntrypoint):

    def fetch(self, request):
        normalizer = Normalizer()

        text = "من کتاب های زیــــادی دارم."

        normalized = normalizer.normalize(text)

        score = fuzz.ratio(
            "سلام دنیا",
            "سلام دنیا!"
        )

        token_score = fuzz.token_sort_ratio(
            "امروز هوا خوب است",
            "هوا امروز خوب است"
        )

        return Response.json({
            "worker": "ok",
            "hazm": {
                "status": "ok",
                "input": text,
                "output": normalized,
            },
            "rapidfuzz": {
                "status": "ok",
                "ratio": score,
                "token_sort_ratio": token_score,
            },
        })