# Переходишь к функции catch_all_messages и меняешь 0 на 4
async def catch_all_messages(message: types.Message):
    from utils import delayed_delete
    asyncio.create_task(delayed_delete(message, 4))
