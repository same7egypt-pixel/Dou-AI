"""إضافة شركة لوجستية جديدة للمنصة.

يُنشئ: Tenant (شركة) + Fleet (أسطول) + حساب دخول COMPANY
ويربطها معاً ثم يطبع بيانات الدخول لتسليمها للعميل.

الاستخدام من داخل مجلد dou-server:
    ./venv/bin/python tools/add_company.py --name "شركة المثال" --phone 966550000000
    # أو بدون خيارات، سيُطلب الإدخال تفاعلياً
"""
import argparse
import sys
from datetime import datetime, timedelta

from app.config import DATABASE_URL
from app.database import SessionLocal
from app.models.entities import Country, Fleet, Tenant, User, UserRole
from app.routers.auth import hash_password

DEFAULT_PASSWORD = "dou123456"
TRIAL_DAYS = 14


def add_company(name: str, phone: str, country: Country) -> None:
    db = SessionLocal()
    try:
        exists = db.query(User).filter(User.phone == phone).first()
        if exists:
            print(f"❌ الرقم {phone} مسجّل مسبقاً")
            return

        now = datetime.utcnow()
        tenant = Tenant(name=name, country=country,
                        plan="TRIAL", monthly_fee=0, billing_day=1,
                        subscription_status="ACTIVE", due_date=now + timedelta(days=TRIAL_DAYS),
                        created_at=now)
        db.add(tenant)
        db.flush()

        fleet = Fleet(tenant_id=tenant.id, name=f"أسطول {name}", zone="", created_at=tenant.created_at)
        db.add(fleet)
        db.flush()

        user = User(
            phone=phone,
            name=f"إدارة {name}",
            password_hash=hash_password(DEFAULT_PASSWORD),
            role=UserRole.COMPANY,
            country=country,
            tenant_id=tenant.id,
            is_active=True,
            created_at=tenant.created_at,
        )
        db.add(user)
        db.commit()

        print("\n✅ شركة جديدة أُنشئت بنجاح. بيانات الدخول:")
        print(f"   • الشركة: {tenant.name}  (ID {tenant.id})")
        print(f"   • الأسطول: {fleet.name}")
        print(f"   • رقم الدخول: {user.phone}")
        print(f"   • كلمة المرور: {DEFAULT_PASSWORD}")
        print(f"   • الخطة: تجربة مجانية {TRIAL_DAYS} يوم (تفعّل الاشتراك قبل انتهائها)")
        print("   • لوحة Fleet: https://dou-platform.onrender.com/fleet.html")
    except Exception as e:
        db.rollback()
        print(f"❌ خطأ: {e}")
    finally:
        db.close()


def prompt_country() -> Country:
    for idx, c in enumerate(Country, start=1):
        print(f"  {idx}) {c.name}")
    choice = input("البلد [1] السعودية / [2] مصر: ").strip()
    return [Country.SA, Country.EG][choice not in ("2", "EG") and 0 or (1 if choice == "2" else 0)]


def main() -> None:
    parser = argparse.ArgumentParser(description="إضافة شركة لوجستية جديدة")
    parser.add_argument("--name", help="اسم الشركة")
    parser.add_argument("--phone", help="رقم الدخول (يبدأ بـ 966)")
    parser.add_argument("--country", choices=["SA", "EG"], default="SA", help="البلد")
    args = parser.parse_args()

    if args.name and args.phone:
        add_company(args.name, args.phone, Country(args.country))
        return

    print(f"قاعدة البيانات: {DATABASE_URL}")
    name = input("اسم الشركة: ").strip()
    if not name:
        print("الاسم مطلوب")
        sys.exit(1)
    phone = input("رقم الدخول (مثلاً 966550000000): ").strip()
    country = prompt_country()
    add_company(name, phone, country)


if __name__ == "__main__":
    main()