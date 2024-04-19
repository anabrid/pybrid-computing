"""
The REDAC network protocol is a request-response message based protocol.
Messages are encoded as JSON strings and delimited by newline characters.
The message definition can be found in the :mod:`.messages` namespace.
Please refer to their documentations and the therein contained sequence diagrams
for details about the messaging process.

A usual sequence of messages for running one or multiple analog computations is:

#. Get the current hardware configuration via a :class:`~.messages.GetEntitiesRequest`.
#. Start a new user session (if required) via a :class:`~.messages.StartSessionRequest`.
#. Configure the analog computation via a series of :class:`~.messages.SetConfigRequest`.
#. Start the analog computation via a :class:`~.messages.StartRunRequest`.
#. Monitor the analog computation by listening to incoming :class:`~.messages.RunStateChangeMessage`
   and :class:`~.messages.RunDataMessage` notifications.
#. The analog computation is done once you receive a :class:`~.messages.RunStateChangeMessage`
   with :attr:`~.messages.RunStateChangeMessage.new` set to :attr:`~..run.RunState.DONE`.
#. Evaluate the data received and repeat from step 3 if necessary.
#. End your session with a :class:`~.messages.EndSessionRequest`.
"""