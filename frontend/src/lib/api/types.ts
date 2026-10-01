export type PublicAddress = {
  line1: string;
  line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
};

export type PublicBusinessSummary = {
  name: string;
  slug: string;
  vertical: string;
  description: string;
  logo_url: string;
};

export type PublicLocation = {
  id: string;
  slug: string;
  name: string;
  timezone: string;
  phone: string;
  email: string;
  address: PublicAddress;
  business: PublicBusinessSummary;
};

export type PublicServiceCategory = {
  slug: string;
  name: string;
};

export type PublicService = {
  id: string;
  slug: string;
  name: string;
  description: string;
  duration_minutes: number;
  price: string;
  currency: string;
  is_bookable_online: boolean;
  category: PublicServiceCategory | null;
};

export type PublicStaffService = {
  id: string;
  slug: string;
  name: string;
  duration_minutes: number;
  price: string;
  currency: string;
};

export type PublicStaff = {
  id: string;
  display_name: string;
  title: string;
  bio: string;
  photo_url: string;
  services: PublicStaffService[];
};

export type PublicSlot = {
  start: string;
  end: string;
  starts_at: string;
  ends_at: string;
  staff_id: string | null;
  staff_options?: string[];
};

export type PublicAvailabilityResponse = {
  location: { id: string; name: string; timezone: string };
  service: {
    id: string;
    name: string;
    duration_minutes: number;
    price: string;
    currency: string;
  };
  date: string;
  slot_grid_minutes: number;
  slots: PublicSlot[];
};

export type PublicCustomerInput = {
  name: string;
  phone: string;
  email?: string;
};

export type PublicAppointmentCreateInput = {
  location_id: string;
  service_id: string;
  staff_id: string | null;
  start: string;
  customer: PublicCustomerInput;
  attribution_source?: string;
  attribution_ref?: string;
};

export type PublicAppointment = {
  public_reference: string;
  status: string;
  service: string;
  location: string;
  staff: string;
  start: string;
  end: string;
  total: string;
  currency: string;
  manage_token?: string;
  payment_status?: string;
  payment_required?: boolean;
  payable_amount?: string | null;
};

export type PublicPaymentOrder = {
  payment_order_id: string;
  provider: string;
  provider_order_id: string;
  amount: number;
  currency: string;
  key_id: string;
  status: string;
};

export type PublicPaymentState = {
  status: string;
  payment_required: boolean;
  currency: string;
  amount: string;
  paid_at: string | null;
  payment_reference: string | null;
};

export type ManagedBooking = {
  public_reference: string;
  status: string;
  location: { name: string; slug: string };
  service: { name: string; duration_minutes: number };
  staff: { name: string };
  starts_at: string;
  ends_at: string;
  customer: { name: string };
  can_cancel: boolean;
  is_regular_booking?: boolean;
  regular_booking?: PublicRegularBooking | null;
};

export type PublicRegularBooking = {
  service_name: string;
  business_name: string;
  location_name: string;
  frequency: string;
  interval: number;
  frequency_label: string;
  preferred_time: string;
  staff_preference: string;
  staff_name: string | null;
  status: string;
  needs_action: boolean;
  needs_action_code: string | null;
  next_appointment: {
    date: string;
    time: string;
    public_reference: string | null;
  } | null;
  timezone: string;
  can_pause?: boolean;
  can_resume?: boolean;
  can_cancel?: boolean;
};

export type PublicBookingPlanCreateInput = PublicAppointmentCreateInput & {
  frequency: "WEEK" | "MONTH";
  interval: number;
  staff_preference?: "SAME_STAFF" | "ANY_STAFF" | null;
  preferred_time?: string | null;
};

export type PublicBookingPlanCreateResponse = PublicAppointment & {
  plan_token?: string;
  regular_booking?: PublicRegularBooking;
};

export type HistoryBooking = {
  public_reference: string;
  status: string;
  category: string;
  location: { name: string; slug: string };
  service: { name: string };
  staff: { name: string };
  starts_at: string;
  ends_at: string;
  can_book_again: boolean;
  is_regular_booking?: boolean;
};

export type BookingHistoryResponse = {
  category: string;
  count: number;
  limit: number;
  offset: number;
  scope_public_reference: string;
  results: HistoryBooking[];
};

export type BookAgainPrefillResponse = {
  available: boolean;
  reason?: string;
  message?: string;
  location: {
    id?: string;
    slug: string;
    name?: string;
  };
  service?: {
    id?: string;
    name: string;
    available?: boolean;
  };
  staff?: {
    id: string;
    name: string;
    available: boolean;
  };
  prefill?: {
    location_id: string;
    service_id: string;
    staff_id: string | null;
  };
};

export type ManagedBookingCancelResponse = {
  public_reference: string;
  status: string;
  message: string;
};

export type Paginated<T> = {
  count: number;
  limit: number;
  offset: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type ApiErrorBody = {
  error: unknown;
  status_code: number;
  code?: string;
};

export type QuickCardHours = {
  weekday: number;
  label: string;
  closed: boolean;
  opens_at: string | null;
  closes_at: string | null;
};

export type QuickCardActions = {
  booking_url: string;
  whatsapp_url: string | null;
  call_url: string | null;
  directions_url: string | null;
  review_url: string | null;
  share_url: string;
};

export type PublicQuickCard = {
  slug: string;
  business: {
    name: string;
    slug?: string;
    description: string;
    address: string;
    timezone: string;
    vertical: string;
    logo?: string;
  };
  location: {
    name: string;
    slug: string;
    timezone: string;
    phone: string;
    email?: string;
    maps_url?: string | null;
    address: PublicAddress;
  };
  quickcard: {
    headline: string;
    description: string;
    logo_url: string;
    cover_image_url: string;
    phone: string;
    whatsapp: string;
    website_url: string;
    google_maps_url: string;
    instagram_url: string;
    facebook_url: string;
  };
  services: PublicService[];
  staff: PublicStaff[];
  hours: QuickCardHours[];
  reviews: null;
  booking: {
    location_slug: string;
    location_id: string;
    booking_url: string;
    booking_path: string;
  };
  actions: QuickCardActions;
  seo: {
    title: string;
    description: string;
    canonical_path: string;
    og_image: string | null;
  };
};

export type QuickCardAnalytics = {
  views: number;
  cta_clicks: {
    book: number;
    whatsapp: number;
    call: number;
    directions: number;
    review: number;
    share: number;
  };
  date_from: string;
  date_to: string;
  bookings: number;
  booking_conversion_rate: number | null;
};

export type ManagedQuickCard = {
  id: string;
  location_id: string;
  slug: string;
  headline: string;
  description: string;
  logo_url: string;
  cover_image_url: string;
  phone: string;
  whatsapp: string;
  website_url: string;
  google_maps_url: string;
  instagram_url: string;
  facebook_url: string;
  is_published: boolean;
  published_at: string | null;
  public_path: string;
  public_url: string;
  booking_url: string;
  location: {
    id: string;
    name: string;
    slug: string;
    timezone: string;
  };
};

export type BusinessSetupSteps = {
  business: boolean;
  location: boolean;
  services: boolean;
  staff: boolean;
  availability: boolean;
  quickcard: boolean;
  publish: boolean;
};

export type BusinessSetupStatus = {
  ready: boolean;
  progress: number;
  completed_steps: number;
  total_steps: number;
  steps: BusinessSetupSteps;
  blocking_reasons: string[];
  business: { id: string; name: string; vertical: string };
  location: {
    id: string;
    name: string;
    slug: string;
    timezone: string;
  } | null;
  locations: {
    id: string;
    name: string;
    slug: string;
    timezone: string;
    is_primary: boolean;
  }[];
  quickcard: {
    slug: string;
    is_published: boolean;
    public_path: string | null;
    public_url: string | null;
  } | null;
  booking_path: string | null;
  booking_url: string | null;
};

export type DashboardAppointment = {
  id: string;
  public_reference: string;
  starts_at: string;
  ends_at: string;
  time_label: string;
  customer_name: string;
  service_name: string;
  staff_name: string;
  status: string;
};

export type BusinessDashboard = {
  business: { id: string; name: string; vertical: string };
  location: BusinessSetupStatus["location"];
  locations: BusinessSetupStatus["locations"];
  setup: {
    ready: boolean;
    progress: number;
    completed_steps: number;
    total_steps: number;
    blocking_reasons: string[];
    steps: BusinessSetupSteps;
  };
  launch?: BusinessLaunchStatus | null;
  today: {
    bookings: number;
    upcoming: number;
    regular_bookings: number;
    local_date?: string;
  };
  appointments: DashboardAppointment[];
  quickcard: BusinessSetupStatus["quickcard"];
  booking_path: string | null;
  booking_url: string | null;
};

export type WebsiteTemplateOption = {
  key: string;
  label: string;
  description: string;
};

export type BusinessLaunchStatus = {
  ready: boolean;
  progress: number;
  completed_steps: number;
  total_steps: number;
  remaining_blocking: number;
  launch_status: "DRAFT" | "READY" | "LIVE";
  checklist: Record<string, boolean>;
  blocking_reasons: string[];
  template: {
    selected: boolean;
    key: string | null;
    options: WebsiteTemplateOption[];
  };
  domain: {
    configured: boolean;
    status: string;
    subdomain: string | null;
    subdomain_hostname: string | null;
    custom_domain: string | null;
    site_root_domain: string;
  };
  google_business: {
    configured: boolean;
    status: string;
    url: string | null;
    review_url?: string | null;
  };
  whatsapp: {
    configured: boolean;
    status: string;
    platform_status: string;
  };
  website: { status: string };
  quickcard: { created: boolean; published: boolean };
  booking: { ready: boolean };
  profile: {
    id: string;
    business_id: string;
    location_id: string;
    template_key: string | null;
    subdomain: string | null;
    subdomain_hostname: string | null;
    public_url: string | null;
    custom_domain: string | null;
    domain_status: string;
    google_business_url: string | null;
    google_review_url: string | null;
    google_business_status: string;
    whatsapp_setup_status: string;
    website_status: string;
    launch_status: string;
  } | null;
  business?: { id: string; name: string; vertical: string };
  location?: BusinessSetupStatus["location"];
  locations?: BusinessSetupStatus["locations"];
};

export type WebsiteTemplateKey = "SALON_MODERN" | "SALON_CLASSIC" | "SALON_LUXURY";

export type PublicSalonSite = {
  template: WebsiteTemplateKey;
  preview: boolean;
  published: boolean;
  business: {
    name: string;
    slug: string;
    category: string;
    vertical: string;
    description: string;
    logo_url: string | null;
  };
  location: {
    name: string;
    slug: string;
    timezone: string;
    address: string | null;
    address_parts: {
      line1: string;
      line2: string;
      city: string;
      state: string;
      postal_code: string;
      country: string;
    };
    city: string;
    phone: string;
  };
  hero: {
    headline: string;
    tagline: string;
    description: string;
    cover_image_url: string | null;
  };
  contact: {
    phone: string | null;
    whatsapp: string | null;
    email: string | null;
  };
  social: {
    website: string | null;
    instagram: string | null;
    facebook: string | null;
    google_maps: string | null;
  };
  services: {
    id: string;
    slug: string;
    name: string;
    description: string;
    duration_minutes: number;
    price: string;
    currency: string;
  }[];
  staff: {
    id: string;
    display_name: string;
    title: string;
    bio: string;
    photo_url: string | null;
    services: { name: string; duration_minutes: number }[];
  }[];
  hours: {
    weekday: number;
    label: string;
    closed: boolean;
    opens_at: string | null;
    closes_at: string | null;
  }[];
  images: { type: string; url: string; alt: string }[];
  booking: { path: string; url: string };
  quickcard: {
    slug: string;
    path: string;
    url: string;
    is_published: boolean;
  } | null;
  site: {
    path: string;
    url: string;
    subdomain: string | null;
    subdomain_hostname: string | null;
  };
  seo: {
    title: string;
    description: string;
    canonical_path: string;
    canonical_url?: string;
    og_image: string | null;
  };
};

export type WebsiteManagementStatus = {
  location_id: string;
  business_id: string;
  template_key: string | null;
  website_status: string;
  domain_status: string;
  launch_status: string;
  subdomain: string | null;
  subdomain_hostname: string | null;
  public_url: string | null;
  internal_path: string;
  custom_domain: string | null;
};

export type GoogleBusinessAccountOption = {
  name: string;
  display_name: string;
  account_type: string | null;
};

export type GoogleBusinessLocationOption = {
  id: string;
  name: string;
  title: string;
  store_code: string | null;
  address: string | null;
  phone: string | null;
  website_uri: string | null;
};

export type GoogleBusinessStatus = {
  id: string;
  business_id: string;
  location_id: string;
  connected: boolean;
  status: string;
  provider: string;
  google_account: { id: string | null; email: string | null };
  google_business_account?: {
    name: string | null;
    selected: boolean;
  };
  google_location?: {
    id: string | null;
    display_name: string | null;
    selected: boolean;
  };
  google_location_id: string | null;
  google_account_id: string | null;
  google_location_display_name?: string | null;
  account_selected?: boolean;
  location_selected: boolean;
  mapped?: boolean;
  synced?: boolean;
  selection_required?: boolean;
  website_sync_available: boolean;
  last_synced_booking_url: string | null;
  last_sync_status: string;
  last_synced_at: string | null;
  connected_at: string | null;
  token_expires_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  website_url: string | null;
  booking_url: string | null;
  syncable: boolean;
  sync_block_reason: string | null;
  oauth_available: boolean;
  authorization_url?: string;
  oauth_started?: boolean;
};

export type WhatsAppConnectionStatus = {
  id: string;
  business_id: string;
  connected: boolean;
  status: string;
  phone_number_id: string | null;
  business_account_id: string | null;
  display_phone_number: string | null;
  verified_name: string | null;
  connected_at: string | null;
  disconnected_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  provider: string;
  connect_available: boolean;
  message_counts?: Record<string, number>;
  reminder_24h?: WhatsAppScheduleStatus;
  reminder_1h?: WhatsAppScheduleStatus;
  review_request?: WhatsAppScheduleStatus & { delay_hours?: number };
  inbound_count?: number;
};

export type WhatsAppScheduleStatus = {
  notification_type: string;
  enabled: boolean;
  status: "ENABLED" | "NOT_CONFIGURED" | string;
  upcoming_count: number;
  delay_hours?: number;
};

export type WhatsAppInboundMessage = {
  id: string;
  customer_name: string | null;
  phone_number: string;
  message_type: string;
  text: string;
  provider_timestamp: string | null;
  processing_status: string;
  created_at: string | null;
};

export type WhatsAppTemplate = {
  id: string;
  business_id: string;
  name: string;
  purpose: string | null;
  language: string;
  category: string;
  status: string;
  provider_status?: string | null;
  body: string;
  variables: string[];
};

export type RecentVisit = {
  appointment_reference: string;
  completed_at: string;
  location: string;
  staff: string;
  service: string;
  price_snapshot: string;
  currency: string;
};

export type ServiceHistoryItem = {
  service_name: string;
  visit_count: number;
  last_visit_at: string;
};

export type StaffHistoryItem = {
  staff_name: string;
  visit_count: number;
  last_visit_at: string;
};

export type LocationHistoryItem = {
  location_name: string;
  visit_count: number;
  last_visit_at: string;
};

export type RetentionSegment =
  | "NO_VISITS"
  | "NEW"
  | "RETURNING"
  | "DUE_FOR_RETURN"
  | "INACTIVE";

export type RetentionAutomationStatus = {
  status: "PENDING" | "QUEUED" | "SENT" | "SKIPPED" | "CANCELLED" | "FAILED";
  scheduled_for: string | null;
  sent_at: string | null;
  skip_reason: string | null;
};

export type RetentionSummary = {
  customer_id: string;
  total_visits: number;
  completed_appointments: number;
  first_visit_at: string | null;
  last_visit_at: string | null;
  days_since_last_visit: number | null;
  average_days_between_visits: number | null;
  segment: RetentionSegment;
  return_after_days: number;
  inactive_after_days: number;
  automation: RetentionAutomationStatus | null;
  visits: RecentVisit[];
  service_history: ServiceHistoryItem[];
  staff_history: StaffHistoryItem[];
  location_history: LocationHistoryItem[];
};

export type RetentionSettings = {
  return_after_days: number;
  inactive_after_days: number;
  due_message_delay_hours: number;
  enabled: boolean;
  updated_at: string;
};

export type CustomerSummary = {
  id: string;
  first_name: string;
  last_name: string;
  full_name: string;
  phone: string;
  email: string;
  total_visits: number;
  first_visit_at: string | null;
  last_visit_at: string | null;
};
