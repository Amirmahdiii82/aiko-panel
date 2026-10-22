-- A receipt (photo/PDF) on a sale too, like purchases and expenses; website orders get their invoice here.
ALTER TABLE sales ADD COLUMN receipt TEXT;
