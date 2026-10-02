from workers import Response, WorkerEntrypoint


class Default(WorkerEntrypoint):

    async def fetch(self, request):
        result = {
            "worker": "ok",
            "packages": {},
        }

        # ---------------------------------------------------------
        # RapidFuzz
        # ---------------------------------------------------------
        try:
            from rapidfuzz import fuzz

            ratio = fuzz.ratio(
                "سلام دنیا",
                "سلام دنیا!"
            )

            token_ratio = fuzz.token_sort_ratio(
                "امروز هوا خوب است",
                "هوا امروز خوب است"
            )

            result["packages"]["rapidfuzz"] = {
                "status": "ok",
                "ratio": ratio,
                "token_sort_ratio": token_ratio,
            }

        except Exception as e:
            result["packages"]["rapidfuzz"] = {
                "status": "error",
                "error": type(e).__name__,
                "message": str(e),
            }

        # ---------------------------------------------------------
        # NLTK
        # ---------------------------------------------------------
        try:
            import nltk

            result["packages"]["nltk"] = {
                "status": "ok",
                "version": nltk.__version__,
            }

        except Exception as e:
            result["packages"]["nltk"] = {
                "status": "error",
                "error": type(e).__name__,
                "message": str(e),
            }

        # ---------------------------------------------------------
        # Hazm
        # ---------------------------------------------------------
        try:
            from hazm import Normalizer

            normalizer = Normalizer()

            original = "من کتاب های زیــــادی دارم."
            normalized = normalizer.normalize(original)

            result["packages"]["hazm"] = {
                "status": "ok",
                "version": "0.12.1",
                "input": original,
                "output": normalized,
            }

        except Exception as e:
            result["packages"]["hazm"] = {
                "status": "error",
                "error": type(e).__name__,
                "message": str(e),
            }

        return Response.json(result)