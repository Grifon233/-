from aiogram.fsm.state import State, StatesGroup

class TrainerStates(StatesGroup):
    waiting_for_schedule_confirmation = State()

class PollStates(StatesGroup):
    waiting_for_answer = State()
    waiting_for_schedule = State()
    waiting_for_no_comment = State()
    waiting_for_comment = State()

class DevStates(StatesGroup):
    waiting_for_new_training = State()
