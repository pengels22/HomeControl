INSERT INTO rooms(name, permanently_open_hvac) VALUES
('Master Bedroom', true), ('Office', true), ('Guest Room', true)
ON CONFLICT (name) DO NOTHING;

INSERT INTO logical_devices(logical_name, device_class) VALUES
('HVAC Fan Call','relay'),('HVAC Cool Call','relay'),('HVAC Heat Call','relay')
ON CONFLICT (logical_name) DO NOTHING;
