// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title OrderEscrow - one escrow contract per shop order (IEP 2025 "Naplata")
/// @notice The shop deploys one instance per order. The customer signs exactly
///         ONE transaction, `pay()`, sending the exact price to the contract.
///         Every other call (binding the courier, releasing the funds after the
///         customer confirms delivery, cancelling) is sent by the owner, who pays
///         its gas. On release the courier receives `courierShareBps / 10000` of
///         the price and the owner the rest; a Complete or Cancelled contract
///         rejects every further call with "Order closed.".
contract OrderEscrow {
    enum State { AwaitingPayment, Funded, InDelivery, Complete, Cancelled }

    address public immutable owner;           // msg.sender at deploy: the shop's key
    address public immutable customer;
    uint256 public immutable price;           // wei; pay() must send exactly this
    uint256 public immutable orderId;
    uint16  public immutable courierShareBps; // 2000 = 20 %
    address public courier;
    State   public state;

    event Funded(address indexed customer, uint256 amount);
    event CourierAssigned(address indexed courier);
    event Completed(uint256 ownerAmount, uint256 courierAmount);
    event Cancelled(uint256 refunded);

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner.");
        _;
    }

    // Declared FIRST on every function so a closed contract always answers "Order closed."
    modifier open() {
        require(state != State.Complete && state != State.Cancelled, "Order closed.");
        _;
    }

    constructor(address _customer, uint256 _price, uint256 _orderId, uint16 _courierShareBps) {
        require(_customer != address(0), "Invalid address.");
        require(_price > 0, "Invalid amount.");
        require(_courierShareBps <= 10000, "Invalid share.");
        owner = msg.sender;
        customer = _customer;
        price = _price;
        orderId = _orderId;
        courierShareBps = _courierShareBps;
        state = State.AwaitingPayment;
    }

    /// @notice The bound customer funds the escrow with exactly `price` wei, once.
    function pay() external payable open {
        require(msg.sender == customer, "Invalid customer.");
        require(state == State.AwaitingPayment, "Transfer already complete.");
        require(msg.value == price, "Invalid amount.");
        state = State.Funded;
        emit Funded(msg.sender, msg.value);
    }

    /// @notice The owner binds the courier who picked the parcel up; only after funding.
    function assignCourier(address _courier) external open onlyOwner {
        require(state == State.Funded, "Transfer not complete.");
        require(_courier != address(0), "Invalid address.");
        courier = _courier;
        state = State.InDelivery;
        emit CourierAssigned(_courier);
    }

    /// @notice Release: courier gets courierShareBps/10000 of the price, owner the rest.
    function confirmDelivery() external open onlyOwner {
        require(state == State.InDelivery, "Delivery not complete.");
        state = State.Complete;                                   // effects BEFORE interactions
        uint256 courierAmount = price * courierShareBps / 10000;
        uint256 ownerAmount = price - courierAmount;              // no rounding loss: sums to price
        (bool okCourier, ) = payable(courier).call{value: courierAmount}("");
        require(okCourier, "Courier transfer failed.");
        (bool okOwner, ) = payable(owner).call{value: ownerAmount}("");
        require(okOwner, "Owner transfer failed.");
        emit Completed(ownerAmount, courierAmount);
    }

    /// @notice Cancel while nothing is in delivery; refunds the customer if funded.
    function cancel() external open onlyOwner {
        require(state == State.AwaitingPayment || state == State.Funded, "Cannot cancel.");
        uint256 refund = address(this).balance;
        state = State.Cancelled;
        if (refund > 0) {
            (bool ok, ) = payable(customer).call{value: refund}("");
            require(ok, "Refund failed.");
        }
        emit Cancelled(refund);
    }

    /// @notice Everything the backend needs in one eth_call.
    function status() external view returns (State, address, address, address, uint256, uint256) {
        return (state, owner, customer, courier, price, address(this).balance);
    }
}
