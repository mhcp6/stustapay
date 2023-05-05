-- revision: 62df6b55
-- requires: null

-- stustapay core database
--
-- (c) 2022-2023 Jonas Jelten <jj@sft.lol>
-- (c) 2022-2023 Leo Fahrbach <leo.fahrbach@stusta.de>
--
-- targets >=postgresql-13
--
-- double-entry bookkeeping for festival payment system.
-- - user identification through tokens
-- - accounts for users, ware input/output and payment providers
-- - products with custom tax rates
-- - till configuration profiles

-- security definer functions are executed in setuid-mode
-- to grant access to them, use:
--   grant execute on function some_function_name to some_insecure_user;

begin;

set plpgsql.extra_warnings to 'all';


-------- tables

-- general key-value config
create table if not exists config (
    key text not null primary key,
    value text
);
insert into config (
    key, value
)
values
    -- event organizer name
    ('bon.issuer', 'der verein'),
    -- event organizer address
    ('bon.addr', E'Müsterstraße 12\n12398 Test Stadt'),
    -- title on top of the bon. This usually is the name of the event like StuStaCulum 2023
    ('bon.title', 'StuStaCulum 2023'),
    -- json array. One of the strings is printed at the end of a bon
    ('bon.closing_texts', '["funny text 0", "funny text 1", "funny text 2", "funny text 3"]'),

    -- Umsatzsteuer ID. Needed on each bon
    ('ust_id', 'DE123456789'),
    ('currency.symbol', '€'),
    ('currency.identifier', 'EUR'),
    ('entry.initial_topup_amount', '8')
    on conflict do nothing;


create table if not exists restriction_type (
    name text not null primary key
);
insert into restriction_type (
    name
)
values
    ('under_18'),
    ('under_16')
    on conflict do nothing;


-- some secret about one or many user_tags
create table if not exists user_tag_secret (
    id bigint primary key generated always as identity,
    key0 bytea not null,
    key1 bytea not null
);


-- for wristbands/cards/...
create table if not exists user_tag (
    -- hardware id of the tag
    uid numeric(20) primary key,
    -- printed on the back
    pin text,
    -- custom serial number secretly stored on each chip
    serial text,
    -- age restriction information
    restriction text references restriction_type(name),

    -- to validate tag authenticity
    -- secret maybe shared with several tags.
    secret bigint references user_tag_secret(id)
);


create table if not exists account_type (
    name text not null primary key
);
insert into account_type (
    name
)
values
    -- for entry/exit accounts
    ('virtual'),

    -- for safe, backpack, ec, ...
    ('internal'),

    -- the one you buy drinks with
    ('private')

    -- todo: cash_drawer, deposit,
    on conflict do nothing;

-- bookkeeping account
create table if not exists account (
    id bigint primary key generated always as identity (start with 1000),
    user_tag_uid numeric(20) unique references user_tag(uid),
    type text not null references account_type(name),
    name text,
    comment text,

    -- current balance, updated on each transaction
    balance numeric not null default 0,
    -- current number of vouchers, updated on each transaction
    vouchers bigint not null default 0

    -- todo: topup-config
);
insert into account (
    id, user_tag_uid, type, name, comment
) overriding system value
values
    -- virtual accounts are hard coded with ids 0-99
    (0, null, 'virtual', 'Sale Exit', 'target account for sales of the system'),
    (1, null, 'virtual', 'Cash Entry', 'source account, when cash is brought in the system (cash top_up, ...)'),
    (2, null, 'virtual', 'Deposit', 'Deposit currently at the customers'),
    (3, null, 'virtual', 'Sumup', 'source account for sumup top up '),
    (4, null, 'virtual', 'Cash Vault', 'Main Cash tresor. At some point cash top up lands here'),
    (5, null, 'virtual', 'Imbalace', 'Imbalance on a cash register on settlement'),
    (6, null, 'virtual', 'Money / Voucher create', 'Account which will be charged on manual account balance updates and voucher top ups'),
    (7, null, 'virtual', 'Cash Exit', 'target account when cash exists the system, e.g. cash pay outs')
    on conflict do nothing;

create table if not exists account_tag_association_history (
    account_id bigint not null references account(id),
    user_tag_uid numeric(20) references user_tag(uid),
    mapping_was_valid_until timestamptz not null default now(),
    primary key (account_id, user_tag_uid, mapping_was_valid_until)
);

create or replace function update_tag_association_history() returns trigger as
$$
begin
    -- this check is already done in the trigger definition but still included here as to not forget it in the future
    if NEW.user_tag_uid = OLD.user_tag_uid or OLD.user_tag_uid is null then
        return NEW;
    end if;
    insert into account_tag_association_history (account_id, user_tag_uid)
    values (NEW.id, OLD.user_tag_uid);
    return NEW;
end
$$ language plpgsql;

create trigger update_tag_association_history_trigger
    after update of user_tag_uid on account
    for each row
    when (OLD.user_tag_uid is distinct from NEW.user_tag_uid and OLD.user_tag_uid is not null)
    execute function update_tag_association_history();

-- people working with the payment system
create table if not exists usr (
    id bigint primary key generated always as identity,

    login text not null unique,
    constraint login_encoding check ( login ~ '[a-zA-Z0-9\-_]+' ),
    password text,

    display_name text not null default '',
    description text,

    user_tag_uid numeric(20) unique references user_tag(uid) on delete restrict,

    transport_account_id bigint references account(id),
    cashier_account_id bigint references account(id)
    -- depending on the transfer action, the correct account is booked

    constraint password_or_user_tag_uid_set check ((user_tag_uid is not null) or (password is not null))
);
comment on column usr.transport_account_id is 'account for orgas to transport cash from one location to another';
comment on column usr.cashier_account_id is 'account for cashiers to store the current cash balance in input or output locations';


create table if not exists usr_session (
    id bigint primary key generated always as identity,
    usr bigint not null references usr(id) on delete cascade
);

create table if not exists customer_session (
    id bigint primary key generated always as identity,
    customer bigint not null references account(id) on delete cascade
);


create table if not exists privilege (
    name text not null primary key
);
insert into privilege (
    name
)
values
    ('account_management'),
    ('cashier_management'),
    ('config_management'),
    ('product_management'),
    ('tax_rate_management'),
    ('user_management'),
    ('till_management'),
    ('order_management'),
    ('terminal_login'),
    ('supervised_terminal_login'),
    ('can_book_orders'),
    ('grant_free_tickets'),
    ('grant_vouchers')
    on conflict do nothing;

create table if not exists user_role (
    id bigint primary key generated always as identity (start with 1000),
    name text not null unique
);

create table if not exists user_to_role (
    user_id bigint not null references usr(id) on delete cascade,
    role_id bigint not null references user_role(id),
    primary key (user_id, role_id)
);

create or replace function user_to_role_updated() returns trigger as
$$
<<locals>> declare
    role_name text;
    user_login text;
    cashier_account_id bigint;
    transport_account_id bigint;
begin
    select name into locals.role_name from user_role where id = NEW.role_id;

    select
        usr.cashier_account_id,
        usr.transport_account_id,
        usr.login
        into locals.cashier_account_id, locals.transport_account_id, locals.user_login
    from usr where id = NEW.user_id;

    if locals.role_name = 'cashier' then
        if locals.cashier_account_id is null then
            insert into account (type, name)
            values ('internal', 'cashier account for ' || locals.user_login)
            returning id into locals.cashier_account_id;

            update usr set cashier_account_id = locals.cashier_account_id where id = NEW.user_id;
        end if;
    end if;
    if locals.role_name = 'finanzorga' then
        if locals.transport_account_id is null then
            insert into account (type, name)
            values ('internal', 'transport account for ' || locals.user_login)
            returning id into locals.transport_account_id;

            update usr set transport_account_id = locals.transport_account_id where id = NEW.user_id;
        end if;
    end if;

    return NEW;
end
$$ language plpgsql;

create trigger user_to_role_updated_trigger
    after insert on user_to_role
    for each row
execute function user_to_role_updated();

create table if not exists user_role_to_privilege (
    role_id bigint not null references user_role(id) on delete cascade,
    privilege text not null references privilege(name),
    primary key (role_id, privilege)
);

insert into user_role (
    id, name
) overriding system value
values
    (0, 'admin'),
    (1, 'finanzorga'),
    (2, 'cashier'),
    (3, 'standleiter'),
    (4, 'infozelt helfer')
on conflict do nothing;

insert into user_role_to_privilege (
    role_id, privilege
)
values
    -- admin
    (0, 'account_management'),
    (0, 'cashier_management'),
    (0, 'config_management'),
    (0, 'product_management'),
    (0, 'tax_rate_management'),
    (0, 'user_management'),
    (0, 'till_management'),
    (0, 'order_management'),
    (0, 'terminal_login'),
    (0, 'grant_free_tickets'),
    (0, 'grant_vouchers'),
    -- finanzorga
    (1, 'account_management'),
    (1, 'cashier_management'),
    (1, 'product_management'),
    (1, 'user_management'),
    (1, 'till_management'),
    (1, 'order_management'),
    (1, 'terminal_login'),
    (1, 'grant_free_tickets'),
    (1, 'grant_vouchers'),
    -- cashier
    (2, 'supervised_terminal_login'),
    (2, 'can_book_orders'),
    -- standleiter
    (3, 'terminal_login'),
    (3, 'grant_vouchers'),
    -- infozelt helfer
    (4, 'supervised_terminal_login'),
    (4, 'grant_free_tickets'),
    (4, 'grant_vouchers');

create or replace view user_role_with_privileges as (
    select
        r.*,
        coalesce(privs.privileges, '{}'::text array) as privileges
    from user_role r
    left join (
        select ur.role_id, array_agg(ur.privilege) as privileges
        from user_role_to_privilege ur
        group by ur.role_id
    ) privs on r.id = privs.role_id
);

create or replace view user_with_roles as (
    select
        usr.*,
        coalesce(roles.roles, '{}'::text array) as role_names
    from usr
    left join (
        select utr.user_id as user_id, array_agg(ur.name) as roles
        from user_to_role utr
        join user_role ur on utr.role_id = ur.id
        group by utr.user_id
    ) roles on usr.id = roles.user_id
);

create or replace view user_with_privileges as (
    select
        usr.*,
        coalesce(privs.privileges, '{}'::text array) as privileges
    from usr
    left join (
        select utr.user_id, array_agg(urtp.privilege) as privileges
        from user_to_role utr
        join user_role_to_privilege urtp on utr.role_id = urtp.role_id
        group by utr.user_id
    ) privs on usr.id = privs.user_id
);

create table if not exists payment_method (
    name text not null primary key
);
insert into payment_method (
    name
)
values
    -- when topping up with cash
    ('cash'),

    -- when topping up with sumup
    ('sumup'),

    -- payment with tag
    ('tag')

    -- todo: paypal

    on conflict do nothing;

create table if not exists order_type(
    name text not null primary key
);
insert into order_type (
    name
)
values
    -- top up customer account
    ('top_up'),
    -- buy items to consume
    ('sale'),
    -- cancel a sale
    ('cancel_sale'),
    -- pay out remaining balance on a tag
    ('pay_out'),
    -- sale of a ticket in combination with an initial top up
    ('ticket')
    on conflict do nothing;


create table if not exists tax (
    name text not null primary key,
    rate numeric not null,
    description text not null
);
insert into tax (
    name, rate, description
)
values
    -- for internal transfers, THIS LINE MUST NOT BE DELETED, EVEN BY AN ADMIN
    ('none', 0.0, 'keine Steuer'),

    -- reduced sales tax for food etc
    -- ermäßigte umsatzsteuer in deutschland
    ('eust', 0.07, 'ermäßigte Umsatzsteuer'),

    -- normal sales tax
    -- umsatzsteuer in deutschland
    ('ust', 0.19, 'normale Umsatzsteuer'),

    -- no tax, when we're the payment system of another legal entity.
    ('transparent', 0.0, 'abgeführt von Begünstigtem')

    on conflict do nothing;


create table if not exists product (
    id bigint primary key generated always as identity (start with 1000),
    -- todo: ean or something for receipt?
    name text not null unique,

    price numeric,
    fixed_price boolean not null default true,
    price_in_vouchers bigint, -- will be null if this product cannot be bought with vouchers
    constraint product_vouchers_only_with_fixed_price check ( price_in_vouchers is not null and fixed_price or price_in_vouchers is null ),
    constraint product_not_fixed_or_price check ( price is not null = fixed_price),
    constraint product_price_in_vouchers_not_zero check ( price_in_vouchers <> 0 ),  -- should be null to avoid divbyzero then

    -- whether the core metadata of this product (price, price_in_vouchers, fixed_price, tax_name and target_account_id) is editable
    is_locked bool not null default false,

    -- whether or not this product
    is_returnable bool not null default false,

    -- if target account is set, the product is booked to this specific account,
    -- e.g. for the deposit account, or a specific exit account (for beer, ...)
    target_account_id bigint references account(id),

    tax_name text not null references tax(name)
);
comment on column product.price is 'price including tax (what is charged in the end)';
comment on column product.fixed_price is 'price is not fixed, e.g for top up. Then price=null and set with the api call';


insert into product (id, name, fixed_price, price, tax_name, is_locked) overriding system value
values
    (1, 'Rabatt', false, null, 'none', true),
    (2, 'Aufladen', false, null, 'none', true),
    (3, 'Auszahlen', false, null, 'none', true),
    (4, 'Eintritt', true, 12, 'ust', true),
    (5, 'Eintritt U18', true, 12, 'ust', true),
    (6, 'Eintritt U16', true, 12, 'ust', true);

-- which products are not allowed to be bought with the user tag restriction (eg beer, below 16)
create table if not exists product_restriction (
    id bigint not null references product(id) on delete cascade,
    restriction text not null references restriction_type(name) on delete cascade,
    unique (id, restriction)
);

create or replace view product_with_tax_and_restrictions as (
    select
        p.*,
        -- price_in_vouchers is never 0 due to constraint product_price_in_vouchers_not_zero
        p.price / p.price_in_vouchers as price_per_voucher,
        tax.rate as tax_rate,
        coalesce(pr.restrictions, '{}'::text array) as restrictions
    from product p
    join tax on p.tax_name = tax.name
    left join (
        select r.id, array_agg(r.restriction) as restrictions
        from product_restriction r
        group by r.id
    ) pr on pr.id = p.id
);

create or replace view product_as_json as (
    select p.id, json_agg(p)->0 as json
    from product_with_tax_and_restrictions p
    group by p.id
);

create table if not exists till_layout (
    id bigint primary key generated always as identity,
    name text not null unique,
    description text
);

create table if not exists till_button (
    id bigint primary key generated always as identity,
    name text not null unique
);

create or replace function check_button_references_locked_products(
    product_id bigint
) returns boolean as
$$
<<locals>> declare
    is_locked boolean;
begin
    select product.is_locked into locals.is_locked
    from product
    where id = check_button_references_locked_products.product_id;
    return locals.is_locked;
end
$$ language plpgsql;

create or replace function check_button_references_max_one_non_fixed_price_product(
    button_id bigint,
    product_id bigint
) returns boolean as
$$
<<locals>> declare
    n_variable_price_products int;
    new_product_is_fixed_price boolean;
begin
    select count(*) into locals.n_variable_price_products
    from till_button_product tlb
    join product p on tlb.product_id = p.id
    where tlb.button_id = check_button_references_max_one_non_fixed_price_product.button_id and not p.fixed_price;

    select product.fixed_price into locals.new_product_is_fixed_price
    from product
    where id = check_button_references_max_one_non_fixed_price_product.product_id;

    return (locals.n_variable_price_products + (not locals.new_product_is_fixed_price)::int) <= 1;
end
$$ language plpgsql;

create or replace function check_button_references_max_one_returnable_product(
    button_id bigint,
    product_id bigint
) returns boolean as
$$
<<locals>> declare
    n_returnable_products int;
    new_product_is_returnable boolean;
begin
    select count(*) into locals.n_returnable_products
    from till_button_product tlb
        join product p on tlb.product_id = p.id
    where tlb.button_id = check_button_references_max_one_returnable_product.button_id and p.is_returnable;

    select product.is_returnable into locals.new_product_is_returnable
    from product
    where id = check_button_references_max_one_returnable_product.product_id;

    return (locals.n_returnable_products + locals.new_product_is_returnable::int) <= 1;
end
$$ language plpgsql;

create or replace function check_button_references_max_one_voucher_product(
    button_id bigint,
    product_id bigint
) returns boolean as
$$
<<locals>> declare
    n_voucher_products int;
    new_product_has_vouchers boolean;
begin
    select count(*) into locals.n_voucher_products
    from till_button_product tlb
        join product p on tlb.product_id = p.id
    where tlb.button_id = check_button_references_max_one_voucher_product.button_id and p.price_in_vouchers is not null;

    select product.price_in_vouchers is not null into locals.new_product_has_vouchers
    from product
    where id = check_button_references_max_one_voucher_product.product_id;

    return (locals.n_voucher_products + locals.new_product_has_vouchers::int) <= 1;
end
$$ language plpgsql;

create table if not exists till_button_product (
    button_id bigint not null references till_button(id) on delete cascade,
    product_id bigint not null references product(id) on delete cascade,
    primary key (button_id, product_id),

    constraint references_only_locked_products check (check_button_references_locked_products(product_id)),
    constraint references_max_one_variable_price_product check (check_button_references_max_one_non_fixed_price_product(button_id, product_id)),
    constraint references_max_one_returnable_product check (check_button_references_max_one_returnable_product(button_id, product_id)),
    constraint references_max_one_voucher_product check (check_button_references_max_one_voucher_product(button_id, product_id))
);

create or replace view till_button_with_products as (
    select
        t.id,
        t.name,
        coalesce(j_view.price, 0) as price, -- sane defaults for buttons without a product
        coalesce(j_view.price_in_vouchers, 0) as price_in_vouchers,
        coalesce(j_view.price_per_voucher, 0) as price_per_voucher,
        coalesce(j_view.fixed_price, true) as fixed_price,
        coalesce(j_view.is_returnable, false) as is_returnable,
        coalesce(j_view.product_ids, '{}'::bigint array) as product_ids
    from till_button t
    left join (
        select
            tlb.button_id,
            sum(coalesce(p.price, 0)) as price,

            -- this assumes that only one product can have a voucher value
            -- because we'd need the products individual voucher prices
            -- and start applying vouchers to the highest price_per_voucher product first.
            sum(coalesce(p.price_in_vouchers, 0)) as price_in_vouchers,
            sum(coalesce(p.price_per_voucher, 0)) as price_per_voucher,

            bool_and(p.fixed_price) as fixed_price, -- a constraint assures us that for variable priced products a button can only refer to one product
            bool_and(p.is_returnable) as is_returnable, -- a constraint assures us that for returnable products a button can only refer to one product
            array_agg(tlb.product_id) as product_ids
        from till_button_product tlb
        join product_with_tax_and_restrictions p on tlb.product_id = p.id
        group by tlb.button_id
        window button_window as (partition by tlb.button_id)
    ) j_view on t.id = j_view.button_id
);

create table if not exists till_layout_to_button (
    layout_id bigint not null references till_layout(id) on delete cascade,
    button_id bigint not null references till_button(id),
    sequence_number bigint not null,
    primary key (layout_id, button_id),
    unique (layout_id, button_id, sequence_number)
);

create or replace view till_layout_with_buttons as (
    select
       t.*,
       coalesce(j_view.button_ids, '{}'::bigint array) as button_ids
    from till_layout t
    left join (
        select tltb.layout_id, array_agg(tltb.button_id order by tltb.sequence_number) as button_ids
        from till_layout_to_button tltb
        group by tltb.layout_id
    ) j_view on t.id = j_view.layout_id
);

create table if not exists till_profile (
    id bigint primary key generated always as identity,
    name text not null unique,
    description text,
    allow_top_up boolean not null default false,
    allow_cash_out boolean not null default false,
    allow_ticket_sale boolean not null default false,
    layout_id bigint not null references till_layout(id)
    -- todo: payment_methods?
);

create table if not exists allowed_user_roles_for_till_profile (
    profile_id bigint not null references till_profile(id) on delete cascade,
    role_id bigint not null references user_role(id),
    primary key (profile_id, role_id)
);

create or replace view till_profile_with_allowed_roles as (
    select
        p.*,
        coalesce(roles.role_ids, '{}'::bigint array) as allowed_role_ids,
        coalesce(roles.role_names, '{}'::text array) as allowed_role_names
    from till_profile p
    left join (
        select a.profile_id, array_agg(ur.id) as role_ids, array_agg(ur.name) as role_names
        from allowed_user_roles_for_till_profile a
        join user_role ur on a.role_id = ur.id
        group by a.profile_id
    ) roles on roles.profile_id = p.id
);

create table if not exists cash_register_stocking (
    id bigint primary key generated always as identity,
    name text not null,
    euro200 bigint not null default 0,
    euro100 bigint not null default 0,
    euro50 bigint not null default 0,
    euro20 bigint not null default 0,
    euro10 bigint not null default 0,
    euro5 bigint not null default 0,
    euro2 bigint not null default 0,
    euro1 bigint not null default 0,
    cent50 bigint not null default 0,
    cent20 bigint not null default 0,
    cent10 bigint not null default 0,
    cent5 bigint not null default 0,
    cent2 bigint not null default 0,
    cent1 bigint not null default 0,
    variable_in_euro numeric not null default 0,
    total numeric generated always as (
        euro200 * 200.0 +
        euro100 * 100.0 +
        euro50 * 50.0 +
        euro20 * 20.0 +
        euro10 * 10.0 +
        euro5 * 5.0 +
        euro2 * 50.0 +
        euro1 * 25.0 +
        cent50 * 20.0 +
        cent20 * 8.0 +
        cent10 * 4.0 +
        cent5 * 2.5 +
        cent2 * 1.0 +
        cent1 * 0.5 +
        variable_in_euro
    ) stored
);
comment on column cash_register_stocking.euro2 is 'number of rolls, one roll = 25 pcs = 50€';
comment on column cash_register_stocking.euro1 is 'number of rolls, one roll = 25 pcs = 25€';
comment on column cash_register_stocking.cent50 is 'number of rolls, one roll = 40 pcs = 20€';
comment on column cash_register_stocking.cent20 is 'number of rolls, one roll = 40 pcs = 8€';
comment on column cash_register_stocking.cent10 is 'number of rolls, one roll = 40 pcs = 4€';
comment on column cash_register_stocking.cent5 is 'number of rolls, one roll = 50 pcs = 2,50€';
comment on column cash_register_stocking.cent2 is 'number of rolls, one roll = 50 pcs = 1€';
comment on column cash_register_stocking.cent1 is 'number of rolls, one roll = 50 pcs = 0,50€';

-- which cash desks do we have and in which state are they
create table if not exists till (
    id bigint primary key generated always as identity,
    name text not null unique,
    description text,
    registration_uuid uuid unique,
    session_uuid uuid unique,

    -- how this till is currently mapped to a tse
    tse_id text,

    -- identifies the current active work shift and configuration
    active_shift text,
    active_profile_id bigint not null references till_profile(id),
    active_user_id bigint references usr(id),
    active_user_role_id bigint references user_role(id),
    constraint user_requires_role check ((active_user_id is null) = (active_user_role_id is null)),

    constraint registration_or_session_uuid_null check ((registration_uuid is null) != (session_uuid is null))
);


create type till_tse_history_type as enum ('register', 'deregister');


-- logs all historic till <-> TSE assignments (as registered with the TSE)
create table if not exists till_tse_history (
    till_name text not null,
    tse_id text not null,
    what till_tse_history_type not null,
    date timestamptz not null default now()
);


create function deny_in_trigger() returns trigger language plpgsql as
$$
begin
  return null;
end;
$$;


create trigger till_tse_history_deny_update_delete
before update or delete on till_tse_history
for each row execute function deny_in_trigger();


-- represents an order of an customer, like buying wares or top up
create table if not exists ordr (
    id bigint primary key generated always as identity,
    uuid uuid not null default gen_random_uuid() unique,

    -- order values can be obtained with order_value

    -- how many line items does this transaction have
    -- determines the next line_item id
    item_count bigint not null default 0,

    booked_at timestamptz not null default now(),

    -- todo: who triggered the transaction (user)

    -- how the order was invoked
    payment_method text not null references payment_method(name),
    -- todo: method_info references payment_information(id) -> (sumup-id, paypal-id, ...)
    --       or inline-json without separate table?

    -- type of the order like, top up, buy beer,
    order_type text not null references order_type(name),
    cancels_order bigint references ordr(id),
    constraint only_cancel_orders_can_reference_orders check((order_type != 'cancel_sale') = (cancels_order is null)),

    -- who created it
    cashier_id bigint not null references usr(id),
    till_id bigint not null references till(id),
    -- customer is allowed to be null, as it is only known on the final booking, not on the creation of the order
    -- canceled orders can have no customer
    customer_account_id bigint references account(id)
);

-- all products in a transaction
create table if not exists line_item (
    order_id bigint not null references ordr(id),
    item_id bigint not null,
    primary key (order_id, item_id),

    product_id bigint not null references product(id),
    -- current product price
    product_price numeric not null,

    quantity bigint not null default 1,
    constraint quantity_not_zero check ( quantity != 0 ),

    -- tax amount
    tax_name text,
    tax_rate numeric,
    total_price numeric generated always as ( product_price * quantity ) stored,
    total_tax numeric generated always as (
        round(product_price * quantity * tax_rate / (1 + tax_rate ), 2)
    ) stored

    -- TODO: constrain that we can only reference locked products
    -- TODO: constrain that only returnable products lead to a non zero quantity here
);

create or replace view line_item_json as (
    select
        l.*,
        row_to_json(p) as product
    from line_item as l
        join product_with_tax_and_restrictions p on l.product_id = p.id
);

create or replace function new_order_added() returns trigger as
$$
begin
    if NEW is null then
        return null;
    end if;

    -- insert a new tse signing request and notify for it
    insert into bon(id) values (NEW.id);
    perform pg_notify('bon', NEW.id::text);

    -- send general notifications, used e.g. for instant UI updates
    perform pg_notify(
        'order',
        json_build_object(
            'order_id', NEW.id,
            'order_uuid', NEW.uuid,
            'cashier_id', NEW.cashier_id,
            'till_id', NEW.till_id
        )::text
    );

    return NEW;
end;
$$ language plpgsql;

drop trigger if exists new_order_trigger on ordr;
create trigger new_order_trigger
    after insert
    on ordr
    for each row
execute function new_order_added();

-- aggregates the line_item's amounts
create or replace view order_value as
    select
        ordr.*,
        sum(total_price) as total_price,
        sum(total_tax) as total_tax,
        sum(total_price - total_tax) as total_no_tax,
        json_agg(line_item_json) as line_items
    from
        ordr
        left join line_item_json
            on (ordr.id = line_item_json.order_id)
    group by
        ordr.id;

-- show all line items
create or replace view order_items as
    select
        ordr.*,
        line_item.*
    from
        ordr
        left join line_item
            on (ordr.id = line_item.order_id);

-- aggregated tax rate of items
create or replace view order_tax_rates as
    select
        ordr.*,
        tax_name,
        tax_rate,
        sum(total_price) as total_price,
        sum(total_tax) as total_tax,
        sum(total_price - total_tax) as total_no_tax
    from
        ordr
        left join line_item
            on (ordr.id = order_id)
        group by
            ordr.id, tax_rate, tax_name;


create table if not exists transaction (
    -- represents a transaction of one account to another
    -- one order can consist of multiple transactions, hence the extra table
    --      e.g. wares to the ware output account
    --      and deposit to a specific deposit account
    id bigint primary key generated always as identity,
    order_id bigint references ordr(id),
    -- for transactions without an associated order we want to track who caused this transaction
    conducting_user_id bigint references usr(id),
    constraint conducting_user_id_or_order_is_set check ((order_id is null) != (conducting_user_id is null)),

    -- what was booked in this transaction  (backpack, items, ...)
    description text,

    source_account bigint not null references account(id),
    target_account bigint not null references account(id),
    constraint source_target_account_different check (source_account != target_account),

    booked_at timestamptz not null default now(),

    -- amount being transferred from source_account to target_account
    amount numeric not null,
    constraint amount_positive check (amount >= 0),
    vouchers bigint not null,
    constraint vouchers_positive check (vouchers >= 0)
);

create table if not exists cashier_shift (
    id bigint primary key generated always as identity,
    -- TODO: constraint that we can only reference users with a cashier account id
    cashier_id bigint references usr(id),
    closing_out_user_id bigint references usr(id),
    started_at timestamptz not null,
    ended_at timestamptz not null,
    final_cash_drawer_balance numeric not null,
    final_cash_drawer_imbalance numeric not null,
    comment text not null,
    close_out_transaction_id bigint not null references transaction(id)
);

create or replace view cashier as (
    select
        usr.id,
        usr.login,
        usr.display_name,
        usr.description,
        usr.user_tag_uid,
        usr.transport_account_id,
        usr.cashier_account_id,
        a.balance as cash_drawer_balance,
        t.id as till_id
    from usr
    join account a on usr.cashier_account_id = a.id
    left join till t on t.active_user_id = usr.id
);


-- book a new transaction and update the account balances automatically, returns the new transaction_id
create or replace function book_transaction (
    order_id bigint,
    description text,
    source_account_id bigint,
    target_account_id bigint,
    amount numeric,
    vouchers_amount bigint,
    booked_at timestamptz default now(),
    conducting_user_id bigint default null
)
    returns bigint as $$
<<locals>> declare
    transaction_id bigint;
    temp_account_id bigint;
begin
    if vouchers_amount * amount < 0 then
        raise 'vouchers_amount and amount must have the same sign';
    end if;

    if amount < 0 or vouchers_amount < 0 then
        -- swap account on negative amount, as only non-negative transactions are allowed
        temp_account_id = source_account_id;
        source_account_id = target_account_id;
        target_account_id = temp_account_id;
        amount = -amount;
        vouchers_amount = -vouchers_amount;
    end if;

    -- add new transaction
    insert into transaction (
        order_id, description, source_account, target_account, amount, vouchers, booked_at, conducting_user_id
    )
    values (
        book_transaction.order_id,
        book_transaction.description,
        book_transaction.source_account_id,
        book_transaction.target_account_id,
        book_transaction.amount,
        book_transaction.vouchers_amount,
        book_transaction.booked_at,
        book_transaction.conducting_user_id
    ) returning id into locals.transaction_id;

    -- update account values
    update account set
        balance = balance - amount,
        vouchers = vouchers - vouchers_amount
        where id = source_account_id;
    update account set
        balance = balance + amount,
        vouchers = vouchers + vouchers_amount
        where id = target_account_id;

    return locals.transaction_id;

end;
$$ language plpgsql;


create type tse_signature_status as enum ('todo', 'pending', 'done', 'failure');
create table tse_signature_status_info (
    enum_value tse_signature_status primary key,
    name text not null,
    description text not null
);


insert into tse_signature_status_info (enum_value, name, description) values
    ('todo', 'todo', 'Signature request is enqueued'),
    ('pending', 'pending', 'Signature is being created by TSE'),
    ('done', 'done', 'Signature was successful'),
    ('failure', 'failure', 'Failed to create signature') on conflict do nothing;


-- requests the tse module to sign something
create table if not exists tse_signature (
    id bigint primary key references ordr(id),

    signature_status tse_signature_status not null default 'todo',
    -- TSE signature result message (error message or success message)
    result_message  text,
    constraint result_message_set check ((result_message is null) = (signature_status = 'todo' or signature_status = 'pending')),

    created timestamptz not null default now(),
    last_update timestamptz not null default now(),

    -- id of the TSE that was used to create the signature
    tse_id          text,
    constraint tse_id_set check ((tse_id is null) = (signature_status = 'todo')),

    -- signature data from the TSE
    tse_transaction text,
    constraint tse_transaction_set check ((tse_transaction is not null) = (signature_status = 'done')),
    tse_signaturenr text,
    constraint tse_signaturenr_set check ((tse_signaturenr is not null) = (signature_status = 'done')),
    tse_start       text,
    constraint tse_start_set check ((tse_start is not null) = (signature_status = 'done')),
    tse_end         text,
    constraint tse_end_set check ((tse_end is not null) = (signature_status = 'done')),
    tse_serial      text,
    constraint tse_serial_set check ((tse_serial is not null) = (signature_status = 'done')),
    tse_hashalgo    text,
    constraint tse_hashalgo_set check ((tse_hashalgo is not null) = (signature_status = 'done')),
    tse_signature   text
    constraint tse_signature_set check ((tse_signature is not null) = (signature_status = 'done'))
);


-- partial index for only the unsigned rows in tse_signature
create index on tse_signature (id) where signature_status = 'todo';
create index on tse_signature (id) where signature_status = 'pending';

create function tse_signature_update_trigger_procedure()
returns trigger as $$
begin
    new.last_update = now();
    return new;
end;
$$ language 'plpgsql';

create or replace trigger tse_signature_update_trigger
    before update
    on
        tse_signature
    for each row
execute procedure tse_signature_update_trigger_procedure();


-- requests the bon generator to create a new receipt
create table if not exists bon (
    id bigint not null primary key references ordr(id),

    generated bool default false,
    generated_at timestamptz,
    status text,
    -- latex compile error
    error text,

    -- output file path
    output_file text
);


-- wooh \o/
commit;
