import cambc as bc
import bot


def main():
    while True:
        try:
            if bc.is_draft():
                bot.draft_turn()
            else:
                bot.play_turn()
        except Exception as e:  # never crash; log line numbers
            tb, where = e.__traceback__, []
            while tb is not None:
                where.append(str(tb.tb_lineno))
                tb = tb.tb_next
            bot.log("turn error: %r at %s" % (e, ">".join(where)))
        bc.end_turn()


main()
