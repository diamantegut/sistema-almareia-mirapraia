# Technical Reference - Reservation Cashier System

## Architecture Overview
The Reservation Cashier System is a module within the Almareia Mirapraia PMS (Property Management System) designed to handle financial transactions specifically related to reservations, distinct from the general reception cashier.

### Core Components
1.  **Backend**: Flask Blueprints (`reception_bp`, `finance_bp`)
2.  **Frontend**: Jinja2 Templates + Bootstrap 5 + Vanilla JS
3.  **Data Store**: JSON Files with Atomic Writes and File Locking
4.  **Services**: `CashierService`, `ReservationService`

## Data Models

### Cashier Session (`cashier_sessions.json`)
Stores the lifecycle of a cashier session.
```json
{
    "id": "uuid",
    "type": "reservation_cashier",
    "status": "open|closed",
    "opened_at": "DD/MM/YYYY HH:MM",
    "closed_at": "DD/MM/YYYY HH:MM",
    "user": "username",
    "initial_balance": 0.0,
    "closing_balance": 0.0,
    "transactions": [
        {
            "amount": 100.0,
            "description": "Payment for Reservation X",
            "type": "sale|deposit|withdrawal",
            "payment_method": "Credit Card",
            "timestamp": "DD/MM/YYYY HH:MM"
        }
    ]
}
```

### Reservation Payment (`reservation_payments.json` - logical link)
Payments are linked to reservations via `transactions` in the cashier session and updated status in `reservations.json`.

## API Endpoints

### 1. Create Manual Reservation
**POST** `/api/reception/create_manual_reservation`
- **Purpose**: Creates a new reservation and optionally processes an initial payment.
- **Payload**:
  ```json
  {
      "guest_name": "John Doe",
      "checkin": "YYYY-MM-DD",
      "checkout": "YYYY-MM-DD",
      "amount": 1000.0,
      "paid_amount": 200.0, // Optional
      "payment_method_id": "1" // Required if paid_amount > 0
  }
  ```
- **Logic**: Validates payment amount vs total. Checks if `reservation_cashier` is open.

### 2. Get Reservation Debt
**GET** `/reception/reservation/<id>/debt`
- **Purpose**: Returns the current debt status of a reservation.
- **Response**:
  ```json
  {
      "total": 1000.0,
      "paid": 200.0,
      "remaining": 800.0
  }
  ```

### 3. Pay Reservation
**POST** `/reception/reservation/pay`
- **Purpose**: Process a payment for an existing reservation.
- **Payload**:
  ```json
  {
      "reservation_id": "uuid",
      "amount": 500.0,
      "payment_method_id": "1"
  }
  ```
- **Logic**: Updates reservation `paid_amount`. Adds transaction to active `reservation_cashier` session.

## Integration Flows

### Reservation Payment Flow
1.  User clicks "Receber Reserva" in `/reception/rooms`.
2.  Frontend fetches debt info via `/debt` endpoint.
3.  User confirms amount and method.
4.  Frontend posts to `/pay`.
5.  Backend:
    -   Validates amount.
    -   Checks active `reservation_cashier` session.
    -   Adds transaction to session.
    -   Updates reservation record.
    -   Returns success.

### Finance Sync
1.  Finance module (`/finance/balances`) calls `get_balance_data`.
2.  `get_balance_data` loads `cashier_sessions.json`.
3.  Filters by `type="reservation_cashier"`.
4.  Aggregates totals and displays in the "Recepção (Reservas)" card.

## Security & Concurrency
-   **File Locking**: All JSON writes are protected by `file_lock` context managers to prevent race conditions.
-   **Session Isolation**: `reservation_cashier` is distinct from `reception_room_billing` to prevent fund mixing.
-   **Idempotency**: Transaction endpoints support `idempotency_key` to prevent double-charging.
