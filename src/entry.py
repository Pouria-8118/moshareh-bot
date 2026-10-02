from workers import Response, WorkerEntrypoint
from rapidfuzz import fuzz


class Default(WorkerEntrypoint):

    async def fetch(self, request):
        score = fuzz.ratio(
            "سلام دنیا",
            "سلام دنیا"
        )

        return Response.json({
            "worker": "ok",
            "rapidfuzz": "ok",
            "test_score": score
        })