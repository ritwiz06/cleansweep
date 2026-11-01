from shopx.registry import register

register("csv", lambda rows: ",".join(rows))
