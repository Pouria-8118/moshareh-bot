from workers import Response, WorkerEntrypoint

from hazm import Normalizer
from rapidfuzz import fuzz


# Initialize once during Worker startup/snapshot.
normalizer = Normalizer()


class Default(WorkerEntrypoint):

    async def fetch(self, request):
        original = "من کتاب های زیــــادی دارم."

        normalized = normalizer.normalize(
            original
        )

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

            "hazm": {
                "status": "ok",
                "input": original,
                "output": normalized,
            },

            "rapidfuzz": {
                "status": "ok",
                "ratio": ratio,
                "token_sort_ratio": token_ratio,
            },
        })