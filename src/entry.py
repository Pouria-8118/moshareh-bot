from workers import Response, WorkerEntrypoint

from hazm import Normalizer
from rapidfuzz import fuzz


# Cloudflare Worker memory is limited to 128 MB.
# Hazm's default Normalizer loads large word/verb dictionaries.
# Disable the dictionary-backed features that this bot does not need
# because the bot has its own normalization pipeline afterwards.
normalizer = Normalizer(
    correct_spacing=False,
    decrease_repeated_chars=False,
    seperate_mi=False,
)


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