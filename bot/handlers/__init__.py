from aiogram import Router

from bot.handlers import (
    add, cleaning, common, edit, freetext, home, meds, menu, recipes, schedule,
    shopping, start, tasks, today,
)

router = Router()
router.include_router(start.router)
router.include_router(home.router)
router.include_router(today.router)
router.include_router(tasks.router)
router.include_router(schedule.router)
router.include_router(menu.router)
router.include_router(recipes.router)
router.include_router(cleaning.router)
router.include_router(meds.router)
router.include_router(shopping.router)
router.include_router(edit.router)
router.include_router(add.router)
router.include_router(common.router)
router.include_router(freetext.router)  # последним — ловит всё, что не команда

__all__ = ["router"]
