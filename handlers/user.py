@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_AUTORESP_TEXT")
async def process_autoresp_text(message: types.Message):
    user_id = message.from_user.id
    # Было 0, ставим 4
    asyncio.create_task(delayed_delete(message, 4))
    # ... остальной код

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_SET_PIN")
async def process_set_pin(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip()
    # Было 5, ставим 4
    asyncio.create_task(delayed_delete(message, 4))
    # ... остальной код

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_UNLOCK_CODE")
async def process_unlock_code(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip()
    # Было 5, ставим 4
    asyncio.create_task(delayed_delete(message, 4))
    # ... остальной код
