from workers import Response, WorkerEntrypoint

from rapidfuzz import fuzz
from hazm import Normalizer


class Default(WorkerEntrypoint):

    async def fetch(self, request):
        normalizer = Normalizer()

        original = "من کتاب های زیــــادی دارم."
        normalized = normalizer.normalize(original)

        ratio = fuzz.ratio(
            "سلام دنیا",
            "سلام دنیا!"
        )

        token_ratio = fuzz.token_sort_ratio(
            "امروز هوا خوب است",
            "هوا امروز خوب است"
        )

        return Response.json({
            "worker": "ok",

            "rapidfuzz": {
                "status": "ok",
                "ratio": ratio,
                "token_sort_ratio": token_ratio,
            },

            "hazm": {
                "status": "ok",
                "input": original,
                "output": normalized,
            },
        })