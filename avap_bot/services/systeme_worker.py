# avap_bot/services/systeme_worker.py
import logging
from threading import Thread
from avap_bot.services.systeme_service import create_contact, apply_tags_bulk

logger = logging.getLogger("avap_bot.systeme_worker")

def enqueue_create_and_tag(email: str, extra: dict = None):
    """
    Fire-and-forget: create contact and apply tags in background thread.
    Use this from your webhook/handler when you do not want to block.
    """
    def job():
        try:
            ok, contact_id, err = create_contact(email, extra)
            if not ok:
                logger.warning("Failed to create Systeme contact for %s: %s", email, err)
                return
            if not contact_id:
                logger.info("Created contact without id for %s — skipping tag apply", email)
                return
            results = apply_tags_bulk(contact_id)
            for tid, (res_ok, res_err) in results.items():
                if res_ok:
                    logger.info("Successfully applied tag %s to contact %s", tid, contact_id)
                else:
                    logger.warning("Failed to apply tag %s to contact %s: %s", tid, contact_id, res_err)
        except Exception as e:
            logger.exception("Unhandled exception in enqueue_create_and_tag: %s", e)

    t = Thread(target=job, daemon=True)
    t.start()
    return t  # caller can keep if they want to join in tests
