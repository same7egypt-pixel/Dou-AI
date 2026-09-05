"""Complete seed for DOU Fleet OS — deterministic demo data for browser testing."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import Base, engine, SessionLocal
from app.models.entities import *
from app.models import intelligence  # noqa: F401
from app.models.merchant import (
    BookingStatus,
    DedicatedShiftBooking,
    MerchantAccount,
    MerchantBranch,
    ShiftType,
)
from app.routers.auth import hash_password
from app.utils.security import generate_merchant_api_key, hash_pin
from datetime import datetime, date, timedelta, time
from decimal import Decimal

DB_PATH = './dou_final_demo/db.sqlite3'
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)

db = SessionLocal()

# ── Users ──
db.add(User(name='DOU Admin', phone='966500000001', password_hash=hash_password('SuperAdmin123!'),
           role=UserRole.DOU_ADMIN, is_active=True, country='SA'))

tenant = Tenant(name='Demo Logistics', country=Country.SA, market_code='SA', default_language='AR',
                currency='SAR', contact_phone='966511111111', plan='GROWTH', monthly_fee=999,
                subscription_status='ACTIVE', customer_type='LOGISTICS')
db.add(tenant); db.flush()

admin = User(name='Company Admin', phone='966511111111', password_hash=hash_password('Company123!'),
             role=UserRole.COMPANY_ADMIN, tenant_id=tenant.id, country='SA', is_active=True)
ops = User(name='Operations', phone='966522222222', password_hash=hash_password('Ops123456!'),
           role=UserRole.OPERATIONS, tenant_id=tenant.id, country='SA', is_active=True)
fin = User(name='Finance', phone='966577777777', password_hash=hash_password('Finance123!'),
           role=UserRole.ACCOUNTANT, tenant_id=tenant.id, country='SA', is_active=True)
sup1 = User(name='Ahmed Supervisor', phone='966533333333', password_hash=hash_password('Super1234!'),
            role=UserRole.SUPERVISOR, tenant_id=tenant.id, country='SA', is_active=True)
db.add_all([admin, ops, fin, sup1]); db.flush()

# ── Geo ──
country = GeoCountry(name='Saudi Arabia', code='SA', active=True); db.add(country); db.flush()
riyadh = GeoCity(country_id=country.id, name='Riyadh', active=True); db.add(riyadh); db.flush()
db.add(TenantOperatingCity(tenant_id=tenant.id, geo_city_id=riyadh.id, display_name='Riyadh', is_active=True)); db.flush()

# ── Org ──
p1 = Project(tenant_id=tenant.id, name='Riyadh Project', is_active=True); db.add(p1); db.flush()
c1 = Contract(tenant_id=tenant.id, project_id=p1.id, name='Main Contract', status='ACTIVE'); db.add(c1); db.flush()
b1 = ContractBranch(tenant_id=tenant.id, contract_id=c1.id, city_id=riyadh.id, city='Riyadh',
                    project_id=p1.id, supervisor_id=sup1.id, is_active=True); db.add(b1); db.flush()

# ── Riders ──
riders_data = [
    {'name': 'Mohamed Ali', 'phone': '966500001111', 'status': 'READY_TO_WORK', 'docs': 'VERIFIED',
     'vehicle': 'COMPLIANT', 'online': True, 'available': True, 'iqama_expiry': date.today() + timedelta(days=120)},
    {'name': 'Omar Hassan', 'phone': '966500002222', 'status': 'READY_TO_WORK', 'docs': 'VERIFIED',
     'vehicle': 'COMPLIANT', 'online': True, 'available': False, 'iqama_expiry': date.today() + timedelta(days=90)},
    {'name': 'Ahmed Said', 'phone': '966500003333', 'status': 'READY_FOR_REVIEW', 'docs': 'PENDING',
     'vehicle': 'NOT_APPLICABLE', 'online': True, 'available': True, 'iqama_expiry': date.today() + timedelta(days=200)},
    {'name': 'Khalid Nasser', 'phone': '966500004444', 'status': 'INCOMPLETE', 'docs': 'PENDING',
     'vehicle': 'NOT_APPLICABLE', 'online': False, 'available': False, 'iqama_expiry': date.today() + timedelta(days=45)},
    {'name': 'Fahad Salem', 'phone': '966500005555', 'status': 'READY_TO_WORK', 'docs': 'VERIFIED',
     'vehicle': 'COMPLIANT', 'online': True, 'available': True, 'iqama_expiry': date.today() + timedelta(days=300)},
]

courier_objs = []
for rd in riders_data:
    c = Courier(
        name=rd['name'], phone=rd['phone'], courier_type=CourierType.COMPANY,
        tenant_id=tenant.id, country=Country.SA, supervisor_id=sup1.id,
        primary_project_id=p1.id, contract_branch_id=b1.id, city_id=riyadh.id,
        is_online=rd['online'], is_available=rd['available'], employment_status='ACTIVE',
        shift_active=True, base_salary=3000, per_delivery_rate=6, bonus_target=500,
        iqama_expiry=rd['iqama_expiry'], license_expiry=date.today() + timedelta(days=180),
        vehicle_license_expiry=date.today() + timedelta(days=200),
        vehicle_type='Motorcycle' if rd['vehicle'] == 'COMPLIANT' else None,
        vehicle_plate=f'ABC {rd["phone"][-4:]}' if rd['vehicle'] == 'COMPLIANT' else None,
        documents_valid=(rd['docs'] == 'VERIFIED'),
    )
    db.add(c); db.flush()
    db.add(User(
        name=rd['name'], phone=rd['phone'], password_hash=hash_password('Rider1234!'),
        role=UserRole.COURIER, tenant_id=tenant.id, courier_id=c.id,
        country='SA', is_active=True
    ))
    db.flush()
    courier_objs.append(c)

# ── Shifts ──
s1 = Shift(tenant_id=tenant.id, name='Morning', zone='Riyadh', start_time='08:00', end_time='16:00',
           required_couriers=3, status=ShiftStatus.ACTIVE,
           courier_ids=str([courier_objs[0].id, courier_objs[1].id, courier_objs[2].id]))
s2 = Shift(tenant_id=tenant.id, name='Evening', zone='Riyadh', start_time='16:00', end_time='00:00',
           required_couriers=2, status=ShiftStatus.ACTIVE,
           courier_ids=str([courier_objs[3].id, courier_objs[4].id]))
db.add_all([s1, s2]); db.flush()

# ── Attendance ──
today = date.today()
att_objs = []
for i, c in enumerate(courier_objs[:3]):
    check_in = datetime.combine(today, datetime.min.time()) + timedelta(hours=8, minutes=5*i)
    att = Attendance(
        courier_id=c.id, shift_id=s1.id, check_in=check_in,
        check_in_lat=24.7136, check_in_lng=46.6753,
        is_late=(i > 0),
    )
    db.add(att)
    att_objs.append(att)
db.flush()

corr1 = AttendanceCorrection(
    tenant_id=tenant.id,
    attendance_id=att_objs[1].id,
    courier_id=courier_objs[1].id,
    requested_by=admin.id,
    original_check_in=att_objs[1].check_in,
    corrected_check_in=datetime.combine(today, datetime.min.time()) + timedelta(hours=8, minutes=0),
    reason="عطل في جهاز البصمة عند المدخل الرئيسي",
    status="PENDING"
)
db.add(corr1)

# ── Vehicles ──
v1 = Vehicle(tenant_id=tenant.id, market_code='SA', plate_number='ABC 123', plate_normalized='ABC123',
             vehicle_type='Motorcycle', operational_status='ACTIVE', compliance_status='COMPLIANT',
             is_exclusive=True, created_at=datetime.now())
v2 = Vehicle(tenant_id=tenant.id, market_code='SA', plate_number='XYZ 789', plate_normalized='XYZ789',
             vehicle_type='Car', operational_status='ACTIVE', compliance_status='COMPLIANT',
             is_exclusive=True, created_at=datetime.now())
v3 = Vehicle(tenant_id=tenant.id, market_code='SA', plate_number='DEF 456', plate_normalized='DEF456',
             vehicle_type='Motorcycle', operational_status='ACTIVE', compliance_status='COMPLIANT',
             is_exclusive=False, created_at=datetime.now())
db.add_all([v1, v2, v3]); db.flush()

db.add(RiderVehicleAssignment(tenant_id=tenant.id, vehicle_id=v1.id, courier_id=courier_objs[0].id,
                              effective_from=date.today(), is_primary=True))
db.add(RiderVehicleAssignment(tenant_id=tenant.id, vehicle_id=v2.id, courier_id=courier_objs[1].id,
                              effective_from=date.today(), is_primary=True))

# ── Document Types ──
dt_iqama = DocumentType(tenant_id=tenant.id, code='IQAMA', name_ar='Iqama', name_en='Iqama',
                        category='IDENTITY', requires_expiry=True, is_active=True)
dt_license = DocumentType(tenant_id=tenant.id, code='LICENSE', name_ar='Driving License',
                          name_en='Driving License', category='LICENSE', requires_expiry=True, is_active=True)
db.add_all([dt_iqama, dt_license]); db.flush()

# ── Documents ──
doc1 = Document(tenant_id=tenant.id, owner_type='COURIER', owner_id=courier_objs[0].id,
                document_type_id=dt_iqama.id, filename='mohamed_iqama.pdf',
                mime_type='application/pdf', storage_key='docs/mohamed_iqama.pdf',
                status='VALID', expiry_date=date.today() + timedelta(days=120),
                created_at=datetime.now())
doc2 = Document(tenant_id=tenant.id, owner_type='COURIER', owner_id=courier_objs[2].id,
                document_type_id=dt_iqama.id, filename='ahmed_iqama.pdf',
                mime_type='application/pdf', storage_key='docs/ahmed_iqama.pdf',
                status='PENDING', expiry_date=date.today() + timedelta(days=200),
                created_at=datetime.now())
doc3 = Document(tenant_id=tenant.id, owner_type='COURIER', owner_id=courier_objs[3].id,
                document_type_id=dt_license.id, filename='khalid_license.pdf',
                mime_type='application/pdf', storage_key='docs/khalid_license.pdf',
                status='PENDING', expiry_date=date.today() + timedelta(days=45),
                created_at=datetime.now())
db.add_all([doc1, doc2, doc3]); db.flush()

# ── Readiness States ──
for i, c in enumerate(courier_objs):
    rd = riders_data[i]
    overall = 'READY' if rd['status'] == 'READY_TO_WORK' else 'RESTRICTED'
    rs = OperationalReadinessState(
        tenant_id=tenant.id, courier_id=c.id, overall_status=overall,
        onboarding_status=rd['status'], employment_status='ACTIVE', account_status='ACTIVE',
        attendance_status='COMPLIANT', shift_status='ASSIGNED',
        availability_status='AVAILABLE' if c.is_available else 'UNAVAILABLE',
        leave_status='NONE', documents_status=rd['docs'],
        vehicle_compliance_status=rd['vehicle'], blockers='[]',
    )
    db.add(rs)

# ── Leave Types & Policies ──
lt_annual = LeaveType(tenant_id=tenant.id, code='ANNUAL', name_ar='إجازة سنوية', name_en='Annual Leave', is_paid=True, max_days_per_year=21, is_active=True)
lt_sick = LeaveType(tenant_id=tenant.id, code='SICK', name_ar='إجازة مرضية', name_en='Sick Leave', is_paid=True, max_days_per_year=14, is_active=True)
lt_emerg = LeaveType(tenant_id=tenant.id, code='EMERGENCY', name_ar='إجازة طارئة', name_en='Emergency Leave', is_paid=False, max_days_per_year=5, is_active=True)
db.add_all([lt_annual, lt_sick, lt_emerg]); db.flush()

pol_annual = LeavePolicy(tenant_id=tenant.id, leave_type_id=lt_annual.id, entitlement_days=21, carryover_limit=5, effective_from=date(today.year, 1, 1), is_active=True)
db.add(pol_annual); db.flush()

# ── Leave Entitlements ──
for c in courier_objs:
    entitle = LeaveEntitlement(tenant_id=tenant.id, courier_id=c.id, leave_type_id=lt_annual.id, year=today.year, entitled_days=21, carried_over_days=0, used_days=0, pending_days=0)
    db.add(entitle)
db.flush()

# ── Leave Requests ──
leave1 = LeaveRequest(
    tenant_id=tenant.id, courier_id=courier_objs[0].id, leave_type_id=lt_annual.id,
    from_date=date.today() + timedelta(days=5), to_date=date.today() + timedelta(days=7),
    reason='مناسبة عائلية', status='PENDING', created_at=datetime.now(),
)
leave2 = LeaveRequest(
    tenant_id=tenant.id, courier_id=courier_objs[1].id, leave_type_id=lt_annual.id,
    from_date=date.today() + timedelta(days=10), to_date=date.today() + timedelta(days=12),
    reason='ظروف خاصة', status='APPROVED', created_at=datetime.now(),
)
db.add_all([leave1, leave2]); db.flush()

# ── Targets ──
target1 = Target(
    tenant_id=tenant.id, scope_type='RIDER', scope_id=courier_objs[0].id,
    target_type='PERFORMANCE', period=today.strftime('%Y-%m'), target_value=500,
    actual_value=420, achievement_percentage=84,
)
target2 = Target(
    tenant_id=tenant.id, scope_type='RIDER', scope_id=courier_objs[1].id,
    target_type='PERFORMANCE', period=today.strftime('%Y-%m'), target_value=500,
    actual_value=510, achievement_percentage=102,
)
db.add_all([target1, target2]); db.flush()

# ── Daily Logs ──
for c in courier_objs[:3]:
    for day_offset in range(7):
        log_date = today - timedelta(days=day_offset)
        orders = 15 + (c.id * 3 + day_offset) % 20
        db.add(DailyLog(tenant_id=tenant.id, courier_id=c.id, project_id=p1.id,
                        log_date=log_date, orders_count=orders))

# ── Bonus Plan ──
bp1 = BonusPlan(
    tenant_id=tenant.id, project_id=p1.id,
    target_orders=500, bonus_amount=2000, over_target_rate=5, is_active=True,
)
db.add(bp1); db.flush()

# ── Payroll Period ──
pp = PayrollPeriod(
    tenant_id=tenant.id, month=today.strftime('%Y-%m'), status='DRAFT',
)
db.add(pp)

# ── Attendance Events ──
for i, c in enumerate(courier_objs[:2]):
    evt = AttendanceEvent(
        tenant_id=tenant.id, courier_id=c.id, event_date=today,
        event_type='LATE' if c.id == courier_objs[1].id else 'PENDING_APPROVAL',
        status='PENDING_APPROVAL', deduction_amount=50 if c.id == courier_objs[1].id else 0,
        idempotency_key=f'evt-{c.id}-{today.isoformat()}',
    )
    db.add(evt)

# ── DOU Flex (Merchant & Branch Pilot) ──
_, prefix, key_hash = generate_merchant_api_key("shawarma")
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
db.add(merchant); db.flush()

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
db.add(branch); db.flush()

booking = DedicatedShiftBooking(
    merchant_branch_id=branch.id,
    logistics_company_tenant_id=tenant.id,
    rider_id=courier_objs[0].id,
    shift_type=ShiftType.full_day_8h,
    shift_start_time=time(12, 0),
    shift_end_time=time(20, 0),
    effective_from=today,
    monthly_fee_to_merchant=Decimal("7000.00"),
    monthly_payout_to_logistics=Decimal("5500.00"),
    dou_margin=Decimal("1500.00"),
    status=BookingStatus.active,
)
db.add(booking); db.flush()

branch_id = branch.id
db.commit()
db.close()

print('✅ Complete demo data created!')
print('Database: ./dou_final_demo/db.sqlite3')
print('')
print('Demo accounts:')
print('  DOU Admin:      966500000001 / SuperAdmin123!')
print('  Company Admin:  966511111111 / Company123!')
print('  Operations:     966522222222 / Ops123456!')
print('  Finance:        966577777777 / Finance123!')
print('  Supervisor:     966533333333 / Super1234!')
print('  Rider / Driver: 966500001111 / Rider1234!')
print(f'  Cashier Portal: Branch: فرع السليمانية - الرياض (ID: {branch_id}) / PIN: 2026')
print('  Merchant Pilot: شاورما كلاسيك (Shawarma Classic) / 7,000 SAR monthly statement')
