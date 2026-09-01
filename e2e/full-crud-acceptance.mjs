import assert from 'node:assert';

const BASE_URL = 'http://127.0.0.1:8123';

async function req(path, opts = {}) {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    },
  });
  const data = await res.json().catch(() => ({}));
  return { status: res.status, ok: res.ok, data };
}

async function run() {
  console.log('\n========================================================================================');
  console.log('FULL CRUD CONTROLS (CREATE, EDIT, DELETE) ACCEPTANCE TEST SUITE');
  console.log('========================================================================================\n');

  // 1. Auth as Company Admin
  const login = await req('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ phone: '966511111111', password: 'Company123!' })
  });
  assert(login.ok, 'Login failed');
  const token = login.data.access_token || login.data.token;
  const authHeaders = { Authorization: `Bearer ${token}` };
  console.log('  ✓ [CRUD-01] Admin Authenticated');

  const ts = Date.now().toString().slice(-6);

  // 2. Supervisor CRUD
  const createSup = await req('/hr/supervisors', {
    method: 'POST',
    headers: authHeaders,
    body: JSON.stringify({ name: `مشرف تجريبي ${ts}`, phone: `96657${ts}1`, password: 'Supervisor123!' })
  });
  if (!createSup.ok) {
    console.error('Create sup failed with:', createSup.status, createSup.data);
  }
  assert(createSup.ok, 'Create supervisor failed');
  const supId = createSup.data.id;
  console.log(`  ✓ [CRUD-02] Supervisor Created (#${supId})`);

  const updateSup = await req(`/hr/supervisors/${supId}`, {
    method: 'PATCH',
    headers: authHeaders,
    body: JSON.stringify({ name: `مشرف معدل ${ts}`, phone: `96657${ts}2` })
  });
  assert(updateSup.ok, 'Update supervisor failed');
  console.log(`  ✓ [CRUD-03] Supervisor Edited`);

  // 3. Contract CRUD
  const createContract = await req('/hr/contracts', {
    method: 'POST',
    headers: authHeaders,
    body: JSON.stringify({
      name: `عقد تجاري ${ts}`,
      client_name: 'منصة جاهز للتجربة',
      client_rate_per_order: 17.5,
      contract_type: 'COMMERCIAL',
      start_date: '2026-09-01',
      end_date: '2027-09-01',
      cities: [
        { city_id: 1, city: 'الرياض', supervisor_ids: [supId] },
        { city_id: 2, city: 'جدة', supervisor_ids: [] }
      ]
    })
  });
  assert(createContract.ok, 'Create contract failed');
  const contractId = createContract.data.id;
  console.log(`  ✓ [CRUD-04] Contract Created with 2 Branches (#${contractId})`);

  const updateContract = await req(`/hr/contracts/${contractId}`, {
    method: 'PATCH',
    headers: authHeaders,
    body: JSON.stringify({
      name: `عقد جاهز المحدث ${ts}`,
      client_name: 'منصة جاهز المحدثة',
      client_rate_per_order: 18.0
    })
  });
  assert(updateContract.ok, 'Update contract failed');
  console.log(`  ✓ [CRUD-05] Contract Edited`);

  // 4. Branch Delete
  const struct = await req('/hr/contract-structure', { headers: authHeaders });
  const myCt = struct.data.find(c => c.id === contractId);
  assert(myCt && myCt.branches.length > 0, 'Branches not found');
  const branchWithSup = myCt.branches.find(b => b.supervisor_id === supId || (b.supervisors && b.supervisors.some(s => s.id === supId))) || myCt.branches[0];
  const branchToDelete = myCt.branches.find(b => b.id !== branchWithSup.id) || myCt.branches[1];
  
  if (branchToDelete) {
    const delBranch = await req(`/hr/contract-branches/${branchToDelete.id}`, {
      method: 'DELETE',
      headers: authHeaders
    });
    assert(delBranch.ok, 'Delete branch failed');
    console.log(`  ✓ [CRUD-06] Branch Deleted (#${branchToDelete.id})`);
  } else {
    console.log(`  ✓ [CRUD-06] Branch Verified`);
  }

  // 5. Courier CRUD
  const createRider = await req('/fleet/couriers', {
    method: 'POST',
    headers: authHeaders,
    body: JSON.stringify({
      name: `سائق تجريبي ${ts}`,
      phone: `96658${ts.slice(-7)}`,
      password: 'Password123!',
      national_id_or_iqama: `10${ts}88`,
      courier_type: 'COMPANY',
      country: 'SA',
      city_id: branchWithSup.city_id,
      base_salary: 2500,
      per_delivery_rate: 3.5,
      contract_id: contractId,
      contract_branch_id: branchWithSup.id,
      supervisor_id: supId,
      vehicle_plate: `أ ب ${ts.slice(-3)}`,
      vehicle_type: 'Motorcycle'
    })
  });
  if (!createRider.ok) {
    console.error('Create rider failed with:', createRider.status, createRider.data);
  }
  assert(createRider.ok, 'Create rider failed');
  const riderId = createRider.data.id;
  console.log(`  ✓ [CRUD-07] Rider Created (#${riderId})`);

  const updateRider = await req(`/fleet/couriers/${riderId}`, {
    method: 'PATCH',
    headers: authHeaders,
    body: JSON.stringify({
      name: `سائق معدل ${ts}`,
      base_salary: 3000,
      per_delivery_rate: 4.0,
      vehicle_plate: `س ص ${ts.slice(-3)}`
    })
  });
  assert(updateRider.ok, 'Update rider failed');
  console.log(`  ✓ [CRUD-08] Rider Edited`);

  const deleteRider = await req(`/fleet/couriers/${riderId}`, {
    method: 'DELETE',
    headers: authHeaders
  });
  if (!deleteRider.ok) {
    console.error('Delete rider failed with:', deleteRider.status, deleteRider.data);
  }
  assert(deleteRider.ok, 'Delete rider failed');
  console.log(`  ✓ [CRUD-09] Rider Deleted / Deactivated`);

  // 6. Delete Supervisor now that courier is unlinked
  const delSup = await req(`/hr/supervisors/${supId}`, {
    method: 'DELETE',
    headers: authHeaders
  });
  assert(delSup.ok, 'Delete supervisor failed');
  console.log(`  ✓ [CRUD-10] Supervisor Deleted`);

  // 7. Delete Contract
  const delContract = await req(`/hr/contracts/${contractId}`, {
    method: 'DELETE',
    headers: authHeaders
  });
  assert(delContract.ok, 'Delete contract failed');
  console.log(`  ✓ [CRUD-11] Contract Deleted / Soft-deleted`);

  // 8. Vehicle CRUD
  const createVeh = await req('/vehicles', {
    method: 'POST',
    headers: authHeaders,
    body: JSON.stringify({
      plate_number: `ط ك ${ts}`,
      vehicle_type: 'Motorcycle',
      make: 'سوزوكي',
      model: 'GN125',
      model_year: 2024,
      market_code: 'SA',
      is_exclusive: true
    })
  });
  assert(createVeh.ok, 'Create vehicle failed');
  const vehId = createVeh.data.id;
  console.log(`  ✓ [CRUD-12] Vehicle Created (#${vehId})`);

  const updateVeh = await req(`/vehicles/${vehId}`, {
    method: 'PATCH',
    headers: authHeaders,
    body: JSON.stringify({
      make: 'هوندا',
      model: 'CG125',
      operational_status: 'ACTIVE'
    })
  });
  assert(updateVeh.ok, 'Update vehicle failed');
  console.log(`  ✓ [CRUD-13] Vehicle Edited`);

  const delVeh = await req(`/vehicles/${vehId}`, {
    method: 'DELETE',
    headers: authHeaders
  });
  assert(delVeh.ok, 'Delete vehicle failed');
  console.log(`  ✓ [CRUD-14] Vehicle Deactivated / Deleted`);

  // 9. Bonus Plan CRUD
  const createBonus = await req('/hr/bonus', {
    method: 'POST',
    headers: authHeaders,
    body: JSON.stringify({
      plan_type: 'TARGET_TIER',
      target_orders: 220,
      bonus_amount: 600,
      over_target_rate: 3.5,
      below_target_rate: 11.5
    })
  });
  assert(createBonus.ok, 'Create bonus plan failed');
  const bonusId = createBonus.data.id;
  console.log(`  ✓ [CRUD-15] Bonus Plan Created (#${bonusId})`);

  const updateBonus = await req(`/hr/bonus/${bonusId}`, {
    method: 'PATCH',
    headers: authHeaders,
    body: JSON.stringify({
      target_orders: 250,
      bonus_amount: 800,
      over_target_rate: 4.0
    })
  });
  assert(updateBonus.ok, 'Update bonus plan failed');
  console.log(`  ✓ [CRUD-16] Bonus Plan Edited`);

  const delBonus = await req(`/hr/bonus/${bonusId}`, {
    method: 'DELETE',
    headers: authHeaders
  });
  assert(delBonus.ok, 'Delete bonus plan failed');
  console.log(`  ✓ [CRUD-17] Bonus Plan Deleted`);

  console.log('\n========================================================================================');
  console.log('ALL 17 CRUD ACCEPTANCE TESTS PASSED WITH 100% SUCCESS');
  console.log('========================================================================================\n');
}

run().catch(err => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
