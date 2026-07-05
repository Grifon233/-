from bot.models.database import get_db, User
from bot.config import ATHLETES, TRAINER_ID, DEVELOPER_ID

def sync_roles():
    with get_db() as db:
        allowed_ids = set(ATHLETES) | {TRAINER_ID, DEVELOPER_ID}

        for tid, data in ATHLETES.items():
            user = db.query(User).filter(User.telegram_id == tid).first()
            if user:
                print(f"Обновление пользователя {tid} ({user.full_name}): {user.role} -> {data['role']}")
                user.role = data['role']
                user.name = data['name']
                user.full_name = data['full_name']
            else:
                print(f"Создание пользователя {tid} ({data['full_name']}) с ролью {data['role']}")
                user = User(
                    telegram_id=tid, 
                    name=data['name'], 
                    full_name=data['full_name'], 
                    role=data['role']
                )
                db.add(user)

        stale_users = db.query(User).filter(~User.telegram_id.in_(allowed_ids)).all()
        for user in stale_users:
            old_role = user.role
            user.role = "inactive"
            user.notifications_enabled = False
            print(f"Деактивация пользователя {user.telegram_id} ({user.full_name or user.name}): {old_role} -> inactive")

        db.commit()
    print("✅ Синхронизация базы данных завершена.")

if __name__ == "__main__":
    sync_roles()
