from workers import Response, WorkerEntrypoint


async def get_sample(db):
    return await db.prepare(
        """
        SELECT
            id,
            poet_name,
            first_letter_canonical,
            last_letter_canonical
        FROM couplets
        ORDER BY id
        LIMIT 1
        """
    ).first()


async def get_state_tables(db):
    return await db.prepare(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        ORDER BY name
        """
    ).all()


class Default(WorkerEntrypoint):

    async def fetch(self, request):
        try:
            sample = await get_sample(
                self.env.CORPUS_1
            )

            state_tables = await get_state_tables(
                self.env.STATE_DB
            )

            return Response.json({
                "worker": "ok",
                "corpus_1_sample": sample,
                "state_tables": [
                    row["name"]
                    for row in state_tables.results
                ]
            })

        except Exception as e:
            return Response.json({
                "worker": "error",
                "error": type(e).__name__,
                "message": str(e)
            }, status=500)
