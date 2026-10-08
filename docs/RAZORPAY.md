# Razorpay in BusinessPOS

With Razorpay connected, checkout has a **Razorpay** payment button. The customer pays
on their phone and BusinessPOS records the payment **only after Razorpay confirms it**.
The cashier doesn't have to watch the soundbox or type a reference number.

| | Plain **UPI** button | **Razorpay** button |
|---|---|---|
| How the customer pays | Scans your own UPI QR | Scans a Razorpay UPI QR, or opens a Razorpay payment link (UPI, debit/credit card, net banking, wallets) |
| Who confirms the payment | The cashier clicks *Payment received* | Razorpay confirms it and BusinessPOS records it by itself |
| Fees | None | Razorpay's fees (see your Razorpay pricing) |
| Internet needed | No | Yes, while the customer is paying |

You can use both. If the internet is down, use Cash or the plain UPI button as usual.

## What you need

- A Razorpay account. Test mode works straight away. Live payments need your account to be
  **activated** (KYC done) in the Razorpay Dashboard.
- Your **API keys**: a *Key ID* (`rzp_test_…` or `rzp_live_…`) and its *Key Secret*.
- For the **UPI QR** option, the *QR Codes* product must be enabled on your Razorpay
  account. If it isn't, BusinessPOS tells you so. Use **Payment link** in the meantime, and
  ask Razorpay support to enable QR Codes.

## 1. Try it in Test Mode first (no real money)

1. In the **Razorpay Dashboard**, switch to **Test Mode** (top of the page).
2. Open **Account & Settings › API Keys** and click **Generate Key**. Copy the *Key ID* and
   the *Key Secret*. Razorpay shows the secret only once.
3. In BusinessPOS, sign in as an administrator and open **Settings › Payments ›
   Razorpay**. Paste the Key ID and Key Secret, then click **Connect**.
   BusinessPOS checks the keys with Razorpay before saving them. The status line
   should read *Connected: TEST mode*.
4. Ring up a sale, click **Checkout**, then click **Razorpay**. A *TEST MODE*
   banner is shown.
   - Click **Payment link**, type your own mobile number and click **Create link**. Open
     the link from the SMS, or scan the QR on screen with your phone's camera. Pay with
     one of the test cards or test UPI IDs that Razorpay lists in its documentation
     (search for *Razorpay test card details*).
   - Within a few seconds BusinessPOS shows *Paid ✓* and adds the payment to the
     checkout. Click **Complete sale**.
   - A UPI QR made in test mode can't be paid from a real UPI app. Test the UPI QR with a
     ₹1 live payment after going live (step 2).
5. Open **Sales**, select the test sale and **void** it, so test payments stay out of your
   accounts.

## 2. Go live

1. In the Razorpay Dashboard, switch to **Live Mode** and generate a **Live** key
   (Account & Settings › API Keys).
2. In BusinessPOS, go to **Settings › Payments › Razorpay**. Click **Disconnect** to remove
   the test key, then enter the live Key ID and Key Secret and click **Connect**. The status
   should read *Connected: Live*.
3. Make a ₹1 test sale with **Razorpay › UPI QR**. Pay it from your own phone and check
   that it shows in the Razorpay Dashboard under **Transactions › Payments**. Then void the
   sale and refund the ₹1 from the Dashboard (see *Refunds* below).

## At the counter

1. In checkout, click **Razorpay**. A UPI QR for the amount due opens immediately.
2. The customer scans it with any UPI app and pays.
3. BusinessPOS checks with Razorpay every few seconds. When the payment is confirmed it
   shows *Paid ✓*, adds the payment (for example *UPI via Razorpay*, `pay_…`) and puts the
   cursor on **Complete sale**.

Other things you can do:

- **The customer wants to pay by card, or the QR doesn't scan:** click **Payment link**.
  The customer can scan the code on screen, or you can type their mobile number to send
  the link by SMS. They can pay by card, UPI or net banking.
- **Split payment:** type the Razorpay part in *Amount* first (for example ₹500 cash
  plus the rest by Razorpay).
- **The customer has already paid, but the window was closed** (or the PC restarted):
  ring the sale up again, click **Razorpay › Already paid? Enter payment ID…** and type
  the `pay_…` ID from the Razorpay Dashboard. BusinessPOS checks with Razorpay that the
  payment is completed, is for the exact amount, and isn't already used on another
  invoice.
- **Cancel:** this closes the QR or link at Razorpay so it can't be paid any more. If the
  customer paid at that very moment, the payment is still found and recorded, never lost.

Safety rules built in:

- A Razorpay payment can't be recorded without a payment ID that Razorpay has confirmed.
- One Razorpay payment can never pay for two invoices.
- If you try to leave checkout after a Razorpay payment has been received, BusinessPOS
  warns you first.

## Daily check

**Sales › Check Razorpay payments…** (also in Settings › Payments) lists every payment
Razorpay received on a day, next to the invoice that recorded it.

- **NOT RECORDED** (red): money arrived but no sale was saved. Ring the sale up again
  using *Already paid? Enter payment ID*, or refund the customer.
- **Not found at Razorpay** (red): a sale says Razorpay but Razorpay has no such payment.
  Look into it.
- *Everything matches ✓*: nothing to do.

## Refunds and voids

BusinessPOS does **not** send refunds to Razorpay by itself. For a return or a voided sale
that was paid through Razorpay:

1. Razorpay Dashboard › **Transactions › Payments** › open the `pay_…` payment ›
   **Issue Refund** (full or partial).
2. In BusinessPOS **Returns**, choose **Razorpay** as the refund method and type the
   refund ID (`rfnd_…`) in the reference box.

## Fees and settlement

Razorpay deducts its fee and settles the rest to your bank account on its settlement
schedule. BusinessPOS records the full bill amount as paid by Razorpay. To include the
fees in your profit & loss, record them under **Expenses**, for example monthly from the
Razorpay settlement report.

## Security

- The Key Secret is encrypted with Windows (DPAPI), so only the same Windows user on the
  same PC can use it. It never appears in settings screens, logs, exports or the audit log.
- A copied database or backup doesn't carry a usable secret. After restoring on a
  different PC, the status says the secret must be entered again.
- Only users with **Manage settings** can connect or disconnect Razorpay. Cashiers can
  take Razorpay payments.
- If you think the Key Secret has leaked, **regenerate** the key in the Razorpay
  Dashboard and connect again with the new one.
- BusinessPOS sends only the amount, your shop name, a short note and (for payment links)
  the customer's mobile number if you type it. It never sees card numbers or UPI PINs.
