#!/usr/bin/env python3
"""
Field Pilot Seed Script for DOU Flex (Dedicated Restaurant Shifts).

Sets up real pilot data:
- Pilot Merchant: "شاورما كلاسيك (Shawarma Classic)"
- Pilot Branch: "فرع السليمانية - الرياض" with GPS geofence (24.7085, 46.6970, 150m) and Cashier PIN (2026)
- Commercial Contract: 8-hour daily dedicated shift
  - Merchant Fee: 7,000 SAR/month
  - Logistics Fleet Payout: 5,500 SAR/month
  - DOU Platform Net Margin: 1,500 SAR/month (21.4%)
- Assigns dedicated courier from logistics company.

Idempotent: Safe to run repeatedly.
"""

from datetime import date, time
from decimal import Decimal

from sqlalchemy import func

from app.database import SessionLocal
from app.models.entities import Courier, Tenant
from app.models.merchant import (
    BookingStatus,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    ShiftType,
)
from app.utils.security import generate_merchant_api_key, hash_pin


def seed_pilot_flex():
    db = SessionLocal()
    try:
        print("🌱 Seeding DOU Flex Field Pilot Data...")

        # 1. Get or pick logistics company tenant
        tenant = (
            db.query(Tenant)
            .join(Courier, Courier.tenant_id == Tenant.id)
            .group_by(Tenant.id)
            .order_by(func.count(Courier.id).desc())
            .first()
        )
        if not tenant:
            tenant = db.query(Tenant).first()
        if not tenant:
            raise RuntimeError("No tenant found. Seed baseline tenant data first.")

        # 2. Pick or ensure an active courier in that tenant
        courier = (
            db.query(Courier)
            .filter(Courier.tenant_id == tenant.id, Courier.employment_status == "ACTIVE")
            .first()
        )
        if not courier:
            from app.models.entities import Country, CourierType
            courier = Courier(
                tenant_id=tenant.id,
                name="فهد المطيري (Fahad Al-Mutairi)",
                phone="0559998877",
                national_id="1098765432",
                courier_type=CourierType.FREELANCER,
                country=Country.SA,
                employment_status="ACTIVE",
            )
            db.add(courier)
            db.flush()

        # 3. Create or update Pilot Merchant Account
        merchant = (
            db.query(MerchantAccount)
            .filter(MerchantAccount.trade_name == "شاورما كلاسيك (Shawarma Classic)")
            .first()
        )
        raw_key = None
        if not merchant:
            raw_key, prefix, key_hash = generate_merchant_api_key("shawarma")
            merchant = MerchantAccount(
                trade_name="شاورما كلاسيك (Shawarma Classic)",
                vat_number="310123456700003",
                billing_contact_email="pilot@shawarmaclassic.com",
                billing_contact_phone="0551234567",
                payment_terms_days=30,
                api_key_prefix=prefix,
                api_key_hash=key_hash,
                is_active=True,
            )
            db.add(merchant)
            db.flush()
            print(f"   ✓ Created Merchant: {merchant.trade_name} (ID: {merchant.id})")
            print(f"     API Key: {raw_key}")
        else:
            print(f"   ✓ Found Existing Merchant: {merchant.trade_name} (ID: {merchant.id})")

        # 4. Create or update Pilot Branch
        branch = (
            db.query(MerchantBranch)
            .filter(
                MerchantBranch.merchant_account_id == merchant.id,
                MerchantBranch.branch_name == "فرع السليمانية - الرياض",
            )
            .first()
        )
        if not branch:
            branch = MerchantBranch(
                merchant_account_id=merchant.id,
                branch_name="فرع السليمانية - الرياض",
                city="الرياض",
                district="السليمانية",
                latitude=Decimal("24.7085000"),
                longitude=Decimal("46.6970000"),
                geofence_radius_meters=150,
                cashier_access_pin=hash_pin("2026"),
                is_active=True,
            )
            db.add(branch)
            db.flush()
            print(f"   ✓ Created Branch: {branch.branch_name} (ID: {branch.id})")
        else:
            # Ensure PIN is 2026 and coordinates are set
            branch.cashier_access_pin = hash_pin("2026")
            branch.latitude = Decimal("24.7085000")
            branch.longitude = Decimal("46.6970000")
            branch.geofence_radius_meters = 150
            branch.is_active = True
            db.flush()
            print(f"   ✓ Updated Branch: {branch.branch_name} (ID: {branch.id})")

        # 5. Create or update DedicatedShiftBooking
        booking = (
            db.query(DedicatedShiftBooking)
            .filter(
                DedicatedShiftBooking.merchant_branch_id == branch.id,
                DedicatedShiftBooking.status == BookingStatus.active,
            )
            .first()
        )
        fee = Decimal("7000.00")
        payout = Decimal("5500.00")
        margin = fee - payout

        if not booking:
            booking = DedicatedShiftBooking(
                merchant_branch_id=branch.id,
                logistics_company_tenant_id=tenant.id,
                rider_id=courier.id,
                shift_type=ShiftType.full_day_8h,
                shift_start_time=time(12, 0),
                shift_end_time=time(20, 0),
                effective_from=date.today(),
                monthly_fee_to_merchant=fee,
                monthly_payout_to_logistics=payout,
                dou_margin=margin,
                status=BookingStatus.active,
            )
            db.add(booking)
            db.commit()
            print(f"   ✓ Created Booking Contract (ID: {booking.id})")
        else:
            booking.rider_id = courier.id
            booking.logistics_company_tenant_id = tenant.id
            booking.monthly_fee_to_merchant = fee
            booking.monthly_payout_to_logistics = payout
            booking.dou_margin = margin
            db.commit()
            print(f"   ✓ Updated Booking Contract (ID: {booking.id})")

        print("\n" + "=" * 60)
        print("🎉 DOU FLEX PILOT ENVIRONMENT READY")
        print("=" * 60)
        print(f"🏪 Restaurant:     {merchant.trade_name}")
        print(f"📍 Branch:         {branch.branch_name}")
        print(f"🔑 Cashier PIN:    2026")
        print(f"🌐 GPS Geofence:   Lat {branch.latitude}, Lng {branch.longitude} (150m)")
        print(f"🏢 Fleet Tenant:   {tenant.name} (ID: {tenant.id})")
        print(f"🛵 Assigned Rider: {courier.name} (ID: {courier.id})")
        print(f"💰 Merchant Fee:   {fee} SAR / month")
        print(f"💵 Fleet Payout:   {payout} SAR / month")
        print(f"📈 DOU Net Margin: {margin} SAR / month ({(margin/fee)*100:.1f}%)")
        if raw_key:
            print(f"🔐 Merchant API:   {raw_key}")
        print("=" * 60 + "\n")

    except Exception as e:
        db.rollback()
        print(f"❌ Error seeding pilot flex: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_pilot_flex()
