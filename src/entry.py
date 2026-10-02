import asyncio

from workers import Response, WorkerEntrypoint


async def count_rows(db):
    row = await db.prepare(
        "SELECT COUNT(*) AS count FROM couplets"
    ).first()

    return row["count"]


class Default(WorkerEntrypoint):

    async def fetch(self, request):
        try:
            counts = await asyncio.gather(
                count_rows(self.env.CORPUS_1),
                count_rows(self.env.CORPUS_2),
                count_rows(self.env.CORPUS_3),
                count_rows(self.env.CORPUS_4),
            )

            state_tables = await self.env.STATE_DB.prepare(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                ORDER BY name
                """
            ).all()

            return Response.json({
                "worker": "ok",
                "corpus_1": counts[0],
                "corpus_2": counts[1],
                "corpus_3": counts[2],
                "corpus_4": counts[3],
                "total": sum(counts),
                "state_tables": [
                    row["name"]
                    for row in state_tables.results
                ]
            })

        except Exception as e:
            return Response.json(
                {
                    "worker": "error",
                    "error": type(e).__name__,
                    "message": str(e)
                },
                status=500
            )
