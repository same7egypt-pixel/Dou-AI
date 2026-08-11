/* DOU Demo Mock API — يعمل محلياً بالكامل بدون سيرفر
   واعي بالدولة: window.DOU_COUNTRY = "SA" (سعودية) أو "EG" (مصر) */
(function(){
  var _realFetch = window.fetch;
  var COUNTRY = (typeof window.DOU_COUNTRY === "string" && (window.DOU_COUNTRY==="EG"||window.DOU_COUNTRY==="SA")) ? window.DOU_COUNTRY : "SA";

  var DB = {
    merchants: [
      /* ===== السعودية ===== */
      {id:1, name:"مقهى بن القهوة", slug:"bin-coffee", theme:"default", delivery_method:"PLATFORM", city:"الرياض", district:"حي الملقا", country:"SA"},
      {id:2, name:"مطعم الضيافة", slug:"diyafa-rest", theme:"dark", delivery_method:"SELF", city:"الرياض", district:"حي العليا", country:"SA"},
      {id:3, name:"بقالة النور", slug:"noor-market", theme:"default", delivery_method:"SHIPPING", city:"الرياض", district:"حي النرجس", country:"SA"},
      {id:4, name:"دار العود للعطور", slug:"dar-oud", theme:"gold", delivery_method:"SHIPPING", city:"الرياض", district:"حي الملقا", country:"SA", category:"عطور"},
      {id:5, name:"متجر الشتاء للملابس", slug:"winter-wear", theme:"default", delivery_method:"SHIPPING", city:"الرياض", district:"حي الملقا", country:"SA", category:"ملابس"},
      {id:6, name:"الرياض للبخور", slug:"riyadh-bakhoor", theme:"gold", delivery_method:"SHIPPING", city:"الرياض", district:"حي النرجس", country:"SA", category:"عطور"},
      /* ===== مصر ===== */
      {id:21, name:"قهوة أبو جبل", slug:"abou-gabal", theme:"default", delivery_method:"PLATFORM", city:"القاهرة", district:"مدينة نصر", country:"EG", category:"قهوة"},
      {id:22, name:"مطعم الحواوشي", slug:"hawawshi-rest", theme:"dark", delivery_method:"PLATFORM", city:"القاهرة", district:"المعادي", country:"EG"},
      {id:23, name:"بقالة السيد", slug:"elsayed-market", theme:"default", delivery_method:"SHIPPING", city:"الجيزة", district:"الدقي", country:"EG"},
      {id:24, name:"بيت العود المصري", slug:"masr-oud", theme:"gold", delivery_method:"SHIPPING", city:"القاهرة", district:"الزمالك", country:"EG", category:"عطور"}
    ],
    products: [
      /* السعودية */
      {id:1, merchant_id:1, name:"كابتشينو", price:16, currency:"SAR", category:"قهوة", is_available:true, description:"إسبريسو بحليب مخفوق"},
      {id:2, merchant_id:1, name:"لاتيه", price:18, currency:"SAR", category:"قهوة", is_available:true, description:"إسبريسو بحليب"},
      {id:3, merchant_id:1, name:"تشيز كيك", price:22, currency:"SAR", category:"حلويات", is_available:true, description:"تشيز كيك بصلصة التوت"},
      {id:4, merchant_id:1, name:"كرواسون", price:14, currency:"SAR", category:"مخبوزات", is_available:true, description:"كرواسون طازج"},
      {id:5, merchant_id:2, name:"مشاوي مشكل", price:45, currency:"SAR", category:"مأكولات", is_available:true, description:"طبق مشاوي"},
      {id:6, merchant_id:2, name:"سلطة سيزر", price:25, currency:"SAR", category:"سلطات", is_available:true, description:"سلطة سيزر بالدجاج"},
      {id:7, merchant_id:3, name:"أرز بسمتي 5كجم", price:34, currency:"SAR", category:"بقالة", is_available:true, description:"أرز بسمتي هندي"},
      {id:8, merchant_id:3, name:"حليب طويل الأجل", price:21, currency:"SAR", category:"بقالة", is_available:true, description:"حليب 1لتر ×6"},
      {id:9, merchant_id:4, name:"عود ملكي 30مل", price:320, currency:"SAR", category:"عطور", is_available:true, description:"عود كمبودي فاخر"},
      {id:10, merchant_id:4, name:"مسك الطهارة", price:95, currency:"SAR", category:"عطور", is_available:true, description:"مسك أبيض نقي"},
      {id:11, merchant_id:4, name:"عطر ليالي الشرق", price:180, currency:"SAR", category:"عطور", is_available:true, description:"عطر شرقي ثابت"},
      {id:12, merchant_id:5, name:"فستان سهرة", price:450, currency:"SAR", category:"ملابس", is_available:true, description:"فستان سهرة أنيق"},
      {id:13, merchant_id:5, name:"عباية فاخرة", price:290, currency:"SAR", category:"ملابس", is_available:true, description:"عباية شيفون مطرزة"},
      {id:14, merchant_id:5, name:"تيشيرت قطني", price:65, currency:"SAR", category:"ملابس", is_available:true, description:"قطن مصري"},
      {id:15, merchant_id:6, name:"بخور عود حرير", price:150, currency:"SAR", category:"بخور", is_available:true, description:"بخور عود فاخر"},
      {id:16, merchant_id:6, name:"معمول عطور مشكل", price:210, currency:"SAR", category:"عطور", is_available:true, description:"تشكيلة عطور شرقية"},
      /* مصر */
      {id:21, merchant_id:21, name:"قهوة سادة", price:15, currency:"EGP", category:"قهوة", is_available:true, description:"قهوة بلدي محمصة"},
      {id:22, merchant_id:21, name:"كابتشينو", price:20, currency:"EGP", category:"قهوة", is_available:true, description:"كابتشينو بالحليب"},
      {id:23, merchant_id:21, name:"سحلب", price:25, currency:"EGP", category:"مشروبات", is_available:true, description:"سحلب بالمكسرات"},
      {id:24, merchant_id:22, name:"حواوشي", price:40, currency:"EGP", category:"مأكولات", is_available:true, description:"حواوشي على الطريقة الإسكندراني"},
      {id:25, merchant_id:22, name:"كشري", price:25, currency:"EGP", category:"مأكولات", is_available:true, description:"كشري مصري أصيل"},
      {id:26, merchant_id:22, name:"طاجن فراخ", price:60, currency:"EGP", category:"مأكولات", is_available:true, description:"طاجن فراخ بالبصل"},
      {id:27, merchant_id:23, name:"أرز مصري 1كجم", price:22, currency:"EGP", category:"بقالة", is_available:true, description:"أرز مصري قصير الحبة"},
      {id:28, merchant_id:23, name:"مكرونة", price:12, currency:"EGP", category:"بقالة", is_available:true, description:"مكرونة إيطالي"},
      {id:29, merchant_id:24, name:"عود مصري 30مل", price:250, currency:"EGP", category:"عطور", is_available:true, description:"عود مصري فاخر"},
      {id:30, merchant_id:24, name:"مسك أبيض", price:120, currency:"EGP", category:"عطور", is_available:true, description:"مسك نقي"},
      {id:31, merchant_id:24, name:"عطر شرقي", price:200, currency:"EGP", category:"عطور", is_available:true, description:"عطر شرقي ثابت"}
    ],
    couriers: [
      {id:1, name:"أحمد الشمري", phone:"0551112233", courier_type:"COMPANY", country:"SA", is_online:true, is_available:true, score:4.9, acceptance_rate:94, current_load:1, lat:24.753, lng:46.641},
      {id:2, name:"محمد العتيبي", phone:"0554445566", courier_type:"FREELANCER", country:"SA", is_online:true, is_available:true, score:4.6, acceptance_rate:88, current_load:0, lat:24.748, lng:46.635},
      {id:3, name:"خالد القحطاني", phone:"0557778899", courier_type:"FREELANCER", country:"SA", is_online:false, is_available:false, score:4.4, acceptance_rate:79, current_load:0, lat:24.76, lng:46.63},
      {id:4, name:"عبدالله السالم", phone:"0552223344", courier_type:"COMPANY", country:"SA", is_online:true, is_available:true, score:4.8, acceptance_rate:91, current_load:2, lat:24.755, lng:46.638},
      {id:21, name:"محمد السيد", phone:"01001112223", courier_type:"FREELANCER", country:"EG", is_online:true, is_available:true, score:4.7, acceptance_rate:90, current_load:1, lat:30.044, lng:31.235},
      {id:22, name:"أحمد عبدالله", phone:"01004445556", courier_type:"COMPANY", country:"EG", is_online:true, is_available:true, score:4.5, acceptance_rate:86, current_load:0, lat:30.05, lng:31.24},
      {id:23, name:"كريم فوزي", phone:"01007778889", courier_type:"FREELANCER", country:"EG", is_online:false, is_available:false, score:4.3, acceptance_rate:81, current_load:0, lat:30.03, lng:31.22}
    ],
    orders: [
      /* السعودية */
      {id:1204, merchant_id:1, customer_name:"سارة", customer_phone:"0551234567", customer_lat:24.752, customer_lng:46.64, customer_address:"حي الملقا، شارع أنس", status:"IN_TRANSIT", delivery_method:"PLATFORM", courier_id:1, subtotal:50, delivery_fee:8, total:58, distance_km:3.2, source:"DOU App", country:"SA"},
      {id:1203, merchant_id:1, customer_name:"نورة", customer_phone:"0553334455", customer_lat:24.757, customer_lng:46.648, customer_address:"حي الملقا", status:"READY", delivery_method:"PLATFORM", courier_id:null, subtotal:34, delivery_fee:8, total:42, distance_km:2.1, source:"Jahez", country:"SA"},
      {id:1202, merchant_id:1, customer_name:"ريم", customer_phone:"0556667788", customer_lat:24.75, customer_lng:46.637, customer_address:"حي الملقا", status:"ACCEPTED", delivery_method:"PLATFORM", courier_id:null, subtotal:40, delivery_fee:8, total:48, distance_km:4.4, source:"HungerStation", country:"SA"},
      {id:1201, merchant_id:1, customer_name:"فيصل", customer_phone:"0559990011", customer_lat:24.749, customer_lng:46.642, customer_address:"حي الملقا", status:"PLACED", delivery_method:"PLATFORM", courier_id:null, subtotal:16, delivery_fee:8, total:24, distance_km:1.8, source:"DOU App", country:"SA"},
      {id:1200, merchant_id:1, customer_name:"هند", customer_phone:"0551213141", customer_lat:24.754, customer_lng:46.641, customer_address:"حي الملقا", status:"DELIVERED", delivery_method:"PLATFORM", courier_id:2, subtotal:70, delivery_fee:8, total:78, distance_km:5.1, source:"Jahez", country:"SA"},
      {id:1199, merchant_id:2, customer_name:"عمر", customer_phone:"0551516171", customer_lat:24.78, customer_lng:46.69, customer_address:"حي العليا", status:"DELIVERED", delivery_method:"SELF", courier_id:null, subtotal:70, delivery_fee:0, total:70, distance_km:0.9, source:"DOU App", country:"SA"},
      {id:1198, merchant_id:3, customer_name:"سلمى", customer_phone:"0551819202", customer_lat:24.82, customer_lng:46.72, customer_address:"حي النرجس", status:"SHIPPING", delivery_method:"SHIPPING", courier_id:null, shipping_company:"SMSA Express", shipping_ref:"SMSA-1198", subtotal:55, delivery_fee:25, total:80, distance_km:18.4, source:"DOU App", country:"SA"},
      {id:1197, merchant_id:4, customer_name:"سارة", customer_phone:"0551234567", customer_lat:24.752, customer_lng:46.64, customer_address:"حي الملقا", status:"DELIVERED", delivery_method:"SHIPPING", courier_id:null, shipping_company:"Bosta", shipping_ref:"BOSTA-1197", subtotal:320, delivery_fee:22, total:342, distance_km:14.2, source:"DOU App", country:"SA"},
      {id:1196, merchant_id:5, customer_name:"سارة", customer_phone:"0551234567", customer_lat:24.752, customer_lng:46.64, customer_address:"حي الملقا", status:"PLACED", delivery_method:"SHIPPING", courier_id:null, shipping_company:null, shipping_ref:null, subtotal:290, delivery_fee:20, total:310, distance_km:12.8, source:"DOU App", country:"SA"},
      /* مصر */
      {id:1304, merchant_id:21, customer_name:"سلمى", customer_phone:"01000000001", customer_lat:30.05, customer_lng:31.35, customer_address:"مدينة نصر، شارع عباس العقاد", status:"IN_TRANSIT", delivery_method:"PLATFORM", courier_id:21, subtotal:40, delivery_fee:15, total:55, distance_km:2.8, source:"DOU App", country:"EG"},
      {id:1303, merchant_id:21, customer_name:"هبة", customer_phone:"01000000002", customer_lat:30.04, customer_lng:31.34, customer_address:"مدينة نصر", status:"READY", delivery_method:"PLATFORM", courier_id:null, subtotal:25, delivery_fee:15, total:40, distance_km:1.6, source:"Jahez", country:"EG"},
      {id:1302, merchant_id:22, customer_name:"أحمد", customer_phone:"01000000003", customer_lat:30.03, customer_lng:31.25, customer_address:"المعادي", status:"DELIVERED", delivery_method:"PLATFORM", courier_id:22, subtotal:85, delivery_fee:15, total:100, distance_km:3.4, source:"DOU App", country:"EG"},
      {id:1301, merchant_id:24, customer_name:"نور", customer_phone:"01000000004", customer_lat:30.06, customer_lng:31.21, customer_address:"الزمالك", status:"SHIPPING", delivery_method:"SHIPPING", courier_id:null, shipping_company:"Bosta", shipping_ref:"BOSTA-1301", subtotal:250, delivery_fee:40, total:290, distance_km:12.1, source:"DOU App", country:"EG"}
    ],
    shifts: [
      {id:1, name:"وردية الصباح", zone:"الملقا", start_time:"09:00", end_time:"17:00", required_couriers:4, status:"ACTIVE"},
      {id:2, name:"وردية المساء", zone:"الملقا", start_time:"17:00", end_time:"01:00", required_couriers:3, status:"SCHEDULED"},
      {id:3, name:"وردية العليا", zone:"العليا", start_time:"10:00", end_time:"18:00", required_couriers:2, status:"ACTIVE"}
    ],
    companies: [
      {id:1, name:"SMSA Express", code:"SMSA", country:"SA", is_active:true},
      {id:2, name:"Bosta", code:"BOSTA", country:"SA", is_active:true},
      {id:3, name:"Aramex", code:"ARAMEX", country:"SA", is_active:false},
      {id:4, name:"Doora", code:"DOORA", country:"EG", is_active:true},
      {id:5, name:"ساعي مصر", code:"SAE", country:"EG", is_active:false}
    ],
    geo: [
      {id:1, name:"السعودية", code:"SA", flag:"🇸🇦", active:true, cities:[
        {id:101, name:"الرياض", active:true, districts:[
          {id:1001, name:"حي الملقا", active:true},
          {id:1002, name:"حي العليا", active:true},
          {id:1003, name:"حي النرجس", active:false}
        ]},
        {id:102, name:"جدة", active:true, districts:[
          {id:1004, name:"حي الحمراء", active:true},
          {id:1005, name:"حي الروضة", active:false}
        ]}
      ]},
      {id:2, name:"مصر", code:"EG", flag:"🇪🇬", active:true, cities:[
        {id:201, name:"القاهرة", active:true, districts:[
          {id:2001, name:"مدينة نصر", active:true},
          {id:2002, name:"المعادي", active:true},
          {id:2003, name:"الزمالك", active:false}
        ]},
        {id:202, name:"الإسكندرية", active:true, districts:[
          {id:2004, name:"سموحة", active:true},
          {id:2005, name:"محرم بك", active:false}
        ]}
      ]}
    ],
    attendance: [],
    channels: [
      {id:1, name:"DOU App", icon:"📱", type:"OWN", commission:0, is_active:true, orders_share:70, status:"active"},
      {id:2, name:"Jahez", icon:"🍔", type:"PARTNER", commission:12, is_active:true, orders_share:18, status:"active"},
      {id:3, name:"HungerStation", icon:"🚀", type:"PARTNER", commission:15, is_active:true, orders_share:8, status:"active"},
      {id:4, name:"POS / نقاط البيع", icon:"🖨", type:"INTEGRATION", commission:2, is_active:true, orders_share:4, status:"active"},
      {id:5, name:"Instagram", icon:"📷", type:"SOCIAL", commission:5, is_active:false, orders_share:0, status:"inactive"},
      {id:6, name:"WhatsApp", icon:"💬", type:"SOCIAL", commission:3, is_active:false, orders_share:0, status:"inactive"},
      {id:7, name:"متجر الكتروني", icon:"🌐", type:"INTEGRATION", commission:2.5, is_active:false, orders_share:0, status:"inactive"}
    ],
    staff: [
      {id:1, name:"سامح صالح", email:"sameh@dou.sa", role:"المؤسس / المدير العام", access:"full", status:"active"},
      {id:2, name:"محمد علي", email:"m.ali@dou.sa", role:"مدير العمليات", access:"ops", status:"active"},
      {id:3, name:"سارة أحمد", email:"s.ahmed@dou.sa", role:"مسؤول مالي", access:"finance", status:"active"},
      {id:4, name:"خالد حسن", email:"k.hassan@dou.sa", role:"مدير منطقة الرياض", access:"region", region:"الرياض", status:"active"},
      {id:5, name:"منى إبراهيم", email:"m.ibrahim@dou.sa", role:"مديرة منطقة القاهرة", access:"region", region:"القاهرة", status:"inactive"}
    ],
    nextId: 1305, nextTask: 51
  };

  function merchantsFor(c){ return DB.merchants.filter(function(m){return m.country===c;}); }
  function couriersFor(c){ return DB.couriers.filter(function(m){return m.country===c;}); }
  function ordersFor(c){ return DB.orders.filter(function(m){return m.country===c;}); }
  function companiesFor(c){ return DB.companies.filter(function(m){return m.country===c;}); }

  function deliverCounts(){
    var done = DB.orders.filter(function(o){return /DELIVER|COMPLETE/i.test(o.status);}).length;
    var total = DB.orders.length;
    return {done:done, total:total};
  }
  function courierDeliveries(cid){
    return DB.orders.filter(function(o){return o.courier_id===cid && /DELIVER|COMPLETE/i.test(o.status);}).length;
  }

  function tasksFor(cid){
    var list = [];
    DB.orders.forEach(function(o){
      if(o.courier_id!==cid) return;
      if(o.status==="OFFERED") list.push({id:DB.nextId + o.id, order_id:o.id, status:"OFFERED"});
      else if(o.status==="ACCEPTED"||o.status==="ASSIGNED") list.push({id:DB.nextId + o.id, order_id:o.id, status:"ACCEPTED"});
      else if(o.status==="PICKED_UP") list.push({id:DB.nextId + o.id, order_id:o.id, status:"ACCEPTED"});
      else if(o.status==="IN_TRANSIT") list.push({id:DB.nextId + o.id, order_id:o.id, status:"ACCEPTED"});
      else if(o.status==="DELIVERED") list.push({id:DB.nextId + o.id, order_id:o.id, status:"DELIVERED"});
    });
    var offered = ordersFor(COUNTRY).filter(function(o){return o.status==="PLACED" && !o.courier_id;});
    offered.slice(0,1).forEach(function(o){
      if(list.length<2) list.unshift({id:DB.nextId+o.id, order_id:o.id, status:"OFFERED"});
    });
    return list;
  }

  function route(method, url, body){
    var u = url.split("?")[0];
    var m = method.toUpperCase();
    if(u==="/health") return {status:"ok", service:"dou-api"};

    if(u==="/merchants" && m==="GET") return merchantsFor(COUNTRY);
    var mm = u.match(/^\/merchants\/(\d+)$/);
    if(mm && m==="GET") return DB.merchants.find(function(x){return x.id==+mm[1];}) || {error:"not found"};
    var mprod = u.match(/^\/merchants\/(\d+)\/products$/);
    if(mprod && m==="GET") return DB.products.filter(function(p){return p.merchant_id==+mprod[1];});
    if(mprod && m==="POST"){ var np={id:DB.nextId++, merchant_id:+mprod[1], name:body.name||"منتج", price:+body.price||0, currency:body.currency||(COUNTRY==="EG"?"EGP":"SAR"), category:body.category||"", is_available:true, description:""}; DB.products.push(np); return np; }
    var mth = u.match(/^\/merchants\/(\d+)\/theme$/);
    if(mth && m==="PATCH"){ var t=DB.merchants.find(function(x){return x.id==+mth[1];}); if(t) t.theme=body.theme; return t||{}; }
    var mdm = u.match(/^\/merchants\/(\d+)\/delivery-method$/);
    if(mdm && m==="PATCH"){ var dm=DB.merchants.find(function(x){return x.id==+mdm[1];}); if(dm) dm.delivery_method=body.delivery_method; return dm||{}; }

    if(u==="/orders" && m==="GET") return ordersFor(COUNTRY);
    if(u==="/orders" && m==="POST"){
      var items=(body.items||[]).map(function(it){
        var p=DB.products.find(function(x){return x.id==+it.product_id;});
        return {product_id:+it.product_id, quantity:it.quantity||1, price:p?p.price:0, name:p?p.name:""};
      });
      var subtotal=items.reduce(function(s,i){return s+i.price*i.quantity;},0);
      var delivery_fee=body.delivery_method==="SHIPPING"?(COUNTRY==="EG"?40:25):(COUNTRY==="EG"?15:8);
      var o={id:DB.nextId++, merchant_id:+body.merchant_id, customer_name:body.customer_name||"عميل",
        customer_phone:body.customer_phone||"0550000000", customer_lat:+body.customer_lat, customer_lng:+body.customer_lng,
        customer_address:body.customer_address||"الرياض", status:"PLACED", delivery_method:"PLATFORM",
        courier_id:null, subtotal:subtotal, delivery_fee:delivery_fee, total:subtotal+delivery_fee,
        distance_km:3.0, source:"DOU App", country:COUNTRY, _items:items};
      DB.orders.push(o);
      return o;
    }
    var om = u.match(/^\/orders\/(\d+)$/);
    if(om && m==="GET") return DB.orders.find(function(o){return o.id==+om[1];}) || {error:"not found"};
    var osm = u.match(/^\/orders\/(\d+)\/status$/);
    if(osm && m==="PATCH"){ var oo=DB.orders.find(function(o){return o.id==+osm[1];}); if(oo) oo.status=body.status; return oo||{}; }

    if(u==="/couriers" && m==="GET") return couriersFor(COUNTRY);
    if(u==="/couriers" && m==="POST"){ var nc={id:DB.couriers.length+100, name:body.name||"مندوب", phone:body.phone||"", courier_type:body.courier_type||"FREELANCER", country:COUNTRY, is_online:false, is_available:false, score:4.0, acceptance_rate:100, current_load:0, lat:+body.lat||(COUNTRY==="EG"?30.04:24.75), lng:+body.lng||(COUNTRY==="EG"?31.23:46.63)}; DB.couriers.push(nc); return nc; }
    var con = u.match(/^\/couriers\/(\d+)\/online$/);
    if(con && m==="POST"){ var co=DB.couriers.find(function(x){return x.id==+con[1];}); if(co){co.is_online=true; co.is_available=true;} return {ok:true}; }
    var coff = u.match(/^\/couriers\/(\d+)\/offline$/);
    if(coff && m==="POST"){ var c2=DB.couriers.find(function(x){return x.id==+coff[1];}); if(c2){c2.is_online=false; c2.is_available=false;} return {ok:true}; }
    var ct = u.match(/^\/couriers\/(\d+)\/tasks$/);
    if(ct && m==="GET") return tasksFor(+ct[1]);
    var ca = u.match(/^\/couriers\/(\d+)\/tasks\/(\d+)\/(accept|reject|deliver)$/);
    if(ca && m==="POST"){
      var oid=+ca[2], cid=+ca[1], act=ca[3];
      var ord=DB.orders.find(function(o){return o.id===oid;});
      if(act==="accept"){ if(ord){ord.status="ASSIGNED"; ord.courier_id=cid;} }
      else if(act==="deliver"){ if(ord){ord.status="DELIVERED"; ord.courier_id=cid;} }
      else if(act==="reject"){ if(ord){ord.status="PLACED"; ord.courier_id=null;} }
      return {ok:true};
    }

    if(u==="/shifts" && m==="GET") return DB.shifts;
    if(u==="/shifts" && m==="POST"){ var ns={id:DB.shifts.length+10, name:body.name||"وردية", zone:body.zone||"", start_time:body.start_time||"09:00", end_time:body.end_time||"17:00", required_couriers:+body.required_couriers||1, status:"SCHEDULED"}; DB.shifts.push(ns); return ns; }
    if(u==="/shifts/attendance/check-in" && m==="POST"){ DB.attendance.push({courier_id:+body.courier_id, in:new Date().toISOString()}); return {ok:true}; }
    if(u==="/shifts/attendance/check-out" && m==="POST"){ return {ok:true}; }

    if(u==="/shipping/companies" && m==="GET") return companiesFor(COUNTRY);
    if(u==="/shipping/companies" && m==="POST"){ var nc2={id:DB.companies.length+100, name:body.name||"", code:body.code||"", country:COUNTRY, is_active:true}; DB.companies.push(nc2); return nc2; }

    /* ===== الجغرافيا: دول / مدن / مناطق ===== */
    if(u==="/geo/countries" && m==="GET") return DB.geo;
    if(u==="/geo/countries" && m==="POST"){ var ng={id:DB.geo.length+50, name:body.name||"دولة جديدة", code:body.code||"XX", flag:body.flag||"🌍", active:true, cities:[]}; DB.geo.push(ng); return ng; }
    var gco = u.match(/^\/geo\/countries\/(\d+)$/);
    if(gco && m==="GET") return DB.geo.find(function(x){return x.id==+gco[1];}) || {error:"not found"};
    if(gco && m==="PATCH"){ var gc=DB.geo.find(function(x){return x.id==+gco[1];}); if(gc) gc.active=!!body.active; return gc||{}; }
    if(gco && m==="DELETE"){ DB.geo = DB.geo.filter(function(x){return x.id!==+gco[1];}); return {ok:true}; }
    var gci = u.match(/^\/geo\/countries\/(\d+)\/cities$/);
    if(gci && m==="POST"){ var g=DB.geo.find(function(x){return x.id==+gci[1];}); if(g){ var nc3={id:Math.floor(300+Math.random()*200), name:body.name||"مدينة جديدة", active:true, districts:[]}; g.cities.push(nc3); return nc3; } return {error:"not found"}; }
    var gct = u.match(/^\/geo\/cities\/(\d+)$/);
    if(gct && m==="GET"){ var cg; DB.geo.forEach(function(c){ c.cities.forEach(function(city){ if(city.id==+gct[1]) cg=city; }); }); return cg||{error:"not found"}; }
    if(gct && m==="PATCH"){ var cc; DB.geo.forEach(function(c){ c.cities.forEach(function(city){ if(city.id==+gct[1]) cc=city; }); }); if(cc) cc.active=!!body.active; return cc||{}; }
    if(gct && m==="DELETE"){ DB.geo.forEach(function(c){ c.cities = c.cities.filter(function(city){ return city.id!==+gct[1]; }); }); return {ok:true}; }
    var gdi = u.match(/^\/geo\/cities\/(\d+)\/districts$/);
    if(gdi && m==="POST"){ var city; DB.geo.forEach(function(c){ c.cities.forEach(function(ci){ if(ci.id==+gdi[1]) city=ci; }); }); if(city){ var nd={id:Math.floor(1000+Math.random()*500), name:body.name||"منطقة جديدة", active:true}; city.districts.push(nd); return nd; } return {error:"not found"}; }
    var gdt = u.match(/^\/geo\/districts\/(\d+)$/);
    if(gdt && m==="GET"){ var dg; DB.geo.forEach(function(c){ c.cities.forEach(function(city){ city.districts.forEach(function(d){ if(d.id==+gdt[1]) dg=d; }); }); }); return dg||{error:"not found"}; }
    if(gdt && m==="PATCH"){ var dd; DB.geo.forEach(function(c){ c.cities.forEach(function(city){ city.districts.forEach(function(d){ if(d.id==+gdt[1]) dd=d; }); }); }); if(dd) dd.active=!!body.active; return dd||{}; }
    if(gdt && m==="DELETE"){ DB.geo.forEach(function(c){ c.cities.forEach(function(city){ city.districts = city.districts.filter(function(d){ return d.id!==+gdt[1]; }); }); }); return {ok:true}; }

    /* ===== Super Admin: كل البيانات عبر الدول ===== */
    if(u==="/admin/merchants" && m==="GET") return DB.merchants;
    if(u==="/admin/merchants" && m==="POST"){
      var nm={id:DB.merchants.length+200, name:body.name||"متجر جديد", slug:(body.slug||"new-store"), theme:"default", delivery_method:body.delivery_method||"PLATFORM", city:body.city||"", district:body.district||"", country:body.country||COUNTRY, category:body.category||"", is_active:true};
      DB.merchants.push(nm); return nm;
    }
    var admM = u.match(/^\/admin\/merchants\/(\d+)$/);
    if(admM && m==="PATCH"){ var am=DB.merchants.find(function(x){return x.id==+admM[1];}); if(am){ if("active" in body) am.is_active=!!body.active; if(body.delivery_method) am.delivery_method=body.delivery_method; if(body.category) am.category=body.category; } return am||{}; }
    if(admM && m==="DELETE"){ DB.merchants = DB.merchants.filter(function(x){return x.id!==+admM[1];}); return {ok:true}; }
    if(u==="/admin/couriers" && m==="GET") return DB.couriers;
    if(u==="/admin/couriers" && m==="POST"){ var nc={id:DB.couriers.length+200, name:body.name||"مندوب جديد", phone:body.phone||"", courier_type:body.courier_type||"FREELANCER", country:body.country||COUNTRY, is_online:false, is_available:true, score:4.0, acceptance_rate:100, current_load:0, is_active:true}; DB.couriers.push(nc); return nc; }
    var admC = u.match(/^\/admin\/couriers\/(\d+)$/);
    if(admC && m==="PATCH"){ var ac=DB.couriers.find(function(x){return x.id==+admC[1];}); if(ac){ if("active" in body) ac.is_active=!!body.active; if(body.courier_type) ac.courier_type=body.courier_type; } return ac||{}; }
    if(admC && m==="DELETE"){ DB.couriers = DB.couriers.filter(function(x){return x.id!==+admC[1];}); return {ok:true}; }
    if(u==="/admin/companies" && m==="GET") return DB.companies;
    if(u==="/admin/companies" && m==="POST"){ var ncmp={id:DB.companies.length+200, name:body.name||"شركة جديدة", code:body.code||"NEW", country:body.country||"SA", is_active:true}; DB.companies.push(ncmp); return ncmp; }
    var admCp = u.match(/^\/admin\/companies\/(\d+)$/);
    if(admCp && m==="PATCH"){ var ap=DB.companies.find(function(x){return x.id==+admCp[1];}); if(ap) ap.is_active = "active" in body ? !!body.active : ap.is_active; return ap||{}; }
    if(admCp && m==="DELETE"){ DB.companies = DB.companies.filter(function(x){return x.id!==+admCp[1];}); return {ok:true}; }
    if(u==="/admin/channels" && m==="GET") return DB.channels;
    if(u==="/admin/channels" && m==="POST"){ var nch={id:DB.channels.length+20, name:body.name||"قناة جديدة", icon:body.icon||"🔌", type:body.type||"PARTNER", commission:+body.commission||0, is_active:true, orders_share:0, status:"active"}; DB.channels.push(nch); return nch; }
    var admCh = u.match(/^\/admin\/channels\/(\d+)$/);
    if(admCh && m==="PATCH"){ var ach=DB.channels.find(function(x){return x.id==+admCh[1];}); if(ach){ if("active" in body){ ach.is_active=!!body.active; ach.status=body.active?"active":"inactive"; } if("commission" in body) ach.commission=+body.commission; } return ach||{}; }
    if(admCh && m==="DELETE"){ DB.channels = DB.channels.filter(function(x){return x.id!==+admCh[1];}); return {ok:true}; }
    if(u==="/admin/staff" && m==="GET") return DB.staff;
    if(u==="/admin/staff" && m==="POST"){ var ns={id:DB.staff.length+10, name:body.name||"موظف جديد", email:body.email||"", role:body.role||"", access:body.access||"limited", status:"active"}; DB.staff.push(ns); return ns; }
    var admS = u.match(/^\/admin\/staff\/(\d+)$/);
    if(admS && m==="PATCH"){ var as=DB.staff.find(function(x){return x.id==+admS[1];}); if(as){ if("active" in body) as.status=body.active?"active":"inactive"; if(body.role) as.role=body.role; } return as||{}; }
    if(admS && m==="DELETE"){ DB.staff = DB.staff.filter(function(x){return x.id!==+admS[1];}); return {ok:true}; }

    if(u==="/analytics/overview"){
      var platform=ordersFor(COUNTRY).filter(function(o){return o.delivery_method==="PLATFORM";}).length;
      var shipping=ordersFor(COUNTRY).filter(function(o){return o.delivery_method==="SHIPPING";}).length;
      var self=ordersFor(COUNTRY).filter(function(o){return o.delivery_method==="SELF";}).length;
      var revenue=ordersFor(COUNTRY).reduce(function(s,o){return s+o.total;},0);
      return {orders_platform:platform, orders_shipping:shipping, orders_self:self,
        deliveries_done:ordersFor(COUNTRY).filter(function(o){return /DELIVER|COMPLETE/i.test(o.status);}).length,
        avg_acceptance:88, avg_score:4.7, revenue_total:revenue};
    }
    if(u==="/analytics/performance"){
      return couriersFor(COUNTRY).map(function(c){
        return {id:c.id, name:c.name, courier_type:c.courier_type, deliveries:courierDeliveries(c.id),
          acceptance_rate:c.acceptance_rate, on_time_rate:c.score>=4.6?95:86, completion_rate:c.score>=4.5?98:90,
          score:c.score, online:c.is_online};
      });
    }
    if(u==="/analytics/payouts"){
      return couriersFor(COUNTRY).map(function(c){
        var d=courierDeliveries(c.id);
        var fixed=c.courier_type==="COMPANY"?4500:0;
        var per= c.courier_type==="COMPANY"?3.5:8.0;
        var earned=d*per;
        var incentive=c.score>=4.7?250:0;
        return {id:c.id, name:c.name, courier_type:c.courier_type, deliveries:d, fixed:fixed,
          per_delivery_earned:earned, incentive:incentive, estimated_total:fixed+earned+incentive};
      });
    }
    if(u==="/analytics/compliance"){
      return {documents_attention:1, attendance_exceptions:2, delivery_investigations:1, couriers_checked_in:3};
    }
    if(u==="/analytics/top-merchants"){
      return merchantsFor(COUNTRY).map(function(m){
        var os=DB.orders.filter(function(o){return o.merchant_id===m.id;});
        return {id:m.id, name:m.name, orders:os.length, revenue:os.reduce(function(s,o){return s+o.total;},0)};
      }).sort(function(a,b){return b.orders-a.orders;});
    }

    return {error:"not found: "+u};
  }

  window.fetch = function(url, opts){
    opts = opts||{};
    var path = typeof url==="string" ? url : (url&&url.url)||"";
    var method = opts.method||"GET";
    var body = opts.body ? JSON.parse(opts.body) : {};
    try{
      var data = route(method, path, body);
      if(data && data.error && data.error.indexOf("not found")===0){
        return Promise.resolve({ok:false, status:404, text:function(){return Promise.resolve(data.error);}, json:function(){return Promise.resolve(data);}});
      }
      return Promise.resolve({ok:true, status:200, text:function(){return Promise.resolve(JSON.stringify(data));}, json:function(){return Promise.resolve(data);}});
    }catch(e){
      return Promise.resolve({ok:false, status:500, text:function(){return Promise.resolve(String(e.message||e));}, json:function(){return Promise.resolve({error:String(e)});}});
    }
  };
})();
