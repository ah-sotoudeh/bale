# How I will run tests (what I'll run in my dev environment)

I cannot run commands inside your environment from here, but below are the exact steps and commands I will run locally to test the full flow using ngrok. You can run the same steps or let me run them in my environment if you prefer.

1) Start Django dev server

    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cp .env config/.env.example  # or use the committed .env in repo
    python manage.py migrate
    python manage.py createsuperuser --username=admin --email=you@example.com
    python manage.py runserver 0.0.0.0:8000

2) Start ngrok (or local tunnel) and get HTTPS URL

    ngrok http 8000

Set BASE_URL to the ngrok HTTPS URL (for example: https://abcd1234.ngrok.io)

3) Point Bale webhooks to:

    {BASE_URL}/api/webhooks/manager-response/
    {BASE_URL}/api/webhooks/payment/

4) Create test data

- Use Django admin (http://127.0.0.1:8000/admin/) to create a User with bale_user_id of "897950525" and a Channel with link "@testchannel" and manager set to that user; create Tariff entries and AvailabilitySlot if needed.

- Alternatively create an Order (in admin) with an OrderItem that has banner_message_id set to a sample id (e.g., "msg-123") and manager pointing to the user above. Make sure order id is 1 for the script examples, or adapt the script with the real ids.

5) Simulate webhooks

    export BASE_URL="https://abcd1234.ngrok.io"
    ./scripts/simulate_webhooks.sh

What I will look for in logs
- Manager-response: server should mark order_item manager_status=approved and when all items decided, move order to waiting_payment and create payment request via bale_client.create_payment_request (you'll see outgoing HTTP call to Bale API in logs).
- Payment webhook: server should set order.status=completed and call bale_client.schedule_message for each order item (or fallback to schedule to manager). The script prints server responses.

If you want, I can run these steps in my environment, start ngrok and run the script, then paste the ngrok URL and sample logs here. Please confirm if you want me to do that, otherwise you can run the script locally and paste any failing logs.
